"""Authorized workflow commands, snapshots, operations and fetch-SSE."""

import asyncio
import base64
import json
import time
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import exists, func, select, tuple_

from foodbridge.agents.orchestrator.service import WorkflowService
from foodbridge.agents.reservation.service import ReservationService
from foodbridge.api.stream import StreamService
from foodbridge.auth.workflow import current_actor
from foodbridge.db.models import Donation, IntakeEvaluation
from foodbridge.db.session import session_factory
from foodbridge.db.workflow import require_role
from foodbridge.db.workflow_models import (
    Assignment,
    Driver,
    Impact,
    MatchOffer,
    Notification,
    TaskFailure,
)
from foodbridge.domain.contracts import DonationRead, ReservationRequest
from foodbridge.domain.errors import AppError
from foodbridge.domain.workflow import (
    Actor,
    DeliveryConfirmation,
    DonationCommand,
    FailurePage,
    FailureRead,
    OfferPage,
    OfferRead,
    OperationsSummary,
    PickupConfirmation,
    PickupPage,
    PickupRead,
    ReplayResult,
    ReservationRead,
    VersionCommand,
)

router = APIRouter(prefix="/api/v1", tags=["workflow"])
Identity = Annotated[Actor, Depends(current_actor)]
Key = Annotated[UUID, Header(alias="Idempotency-Key")]
Limit = Annotated[int, Query(ge=1, le=100)]


def reservation(request):
    return ReservationService(
        request.app.state.settings.database_url,
        request.app.state.clock,
        allow_synthetic=request.app.state.settings.enable_local_workflow_demo,
    )


def coordinator(request):
    return WorkflowService(
        request.app.state.settings.database_url,
        request.app.state.clock,
        allow_synthetic=request.app.state.settings.enable_local_workflow_demo,
    )


def page_query(query, model, limit, cursor, session):
    if cursor:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            stamp, identifier = datetime.fromisoformat(value[0]), UUID(value[1])
            if stamp.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError, IndexError, KeyError) as exc:
            raise AppError("invalid_cursor", "Invalid page cursor.", 400) from exc
        query = query.where(tuple_(model.created_at, model.id) > tuple_(stamp, identifier))
    rows = list(session.scalars(query.order_by(model.created_at, model.id).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps([rows[-1].created_at.isoformat(), str(rows[-1].id)]).encode()
        ).decode()
        if has_more
        else None
    )
    return rows, next_cursor


@router.get("/session", response_model=Actor)
def session_identity(actor: Identity):
    return actor


@router.post("/reservations", response_model=ReservationRead, status_code=201)
def reserve(body: ReservationRequest, request: Request, actor: Identity, key: Key):
    return reservation(request).reserve(actor, body, key, request.state.request_id)


@router.post("/matches/{identifier}/decline", response_model=DonationRead)
def decline(identifier: UUID, body: VersionCommand, request: Request, actor: Identity, key: Key):
    return reservation(request).decline(actor, identifier, body, key, request.state.request_id)


@router.post("/reservations/{identifier}/release", response_model=ReservationRead)
def release(identifier: UUID, body: VersionCommand, request: Request, actor: Identity, key: Key):
    return reservation(request).release(actor, identifier, body, key, request.state.request_id)


@router.post("/donations/{identifier}/cancel", response_model=DonationRead)
def cancel(identifier: UUID, body: DonationCommand, request: Request, actor: Identity, key: Key):
    return reservation(request).cancel(actor, identifier, body, key, request.state.request_id)


@router.post("/pickups/{identifier}/accept", response_model=PickupRead)
def accept_pickup(
    identifier: UUID, body: VersionCommand, request: Request, actor: Identity, key: Key
):
    return reservation(request).pickup_command(
        actor, identifier, "accept", body, key, request.state.request_id
    )


@router.post("/pickups/{identifier}/decline", response_model=PickupRead)
def decline_pickup(
    identifier: UUID, body: VersionCommand, request: Request, actor: Identity, key: Key
):
    return reservation(request).pickup_command(
        actor, identifier, "decline", body, key, request.state.request_id
    )


@router.post("/pickups/{identifier}/confirm-pickup", response_model=PickupRead)
def confirm_pickup(
    identifier: UUID, body: PickupConfirmation, request: Request, actor: Identity, key: Key
):
    return reservation(request).pickup_command(
        actor, identifier, "confirm-pickup", body, key, request.state.request_id
    )


@router.post("/pickups/{identifier}/confirm-delivery", response_model=PickupRead)
def confirm_delivery(
    identifier: UUID, body: DeliveryConfirmation, request: Request, actor: Identity, key: Key
):
    return reservation(request).pickup_command(
        actor, identifier, "confirm-delivery", body, key, request.state.request_id
    )


@router.get("/matches", response_model=OfferPage)
def offers(request: Request, actor: Identity, limit: Limit = 25, cursor: str | None = None):
    require_role(actor, "recipient")
    with session_factory(request.app.state.settings.database_url)() as session:
        rows, next_cursor = page_query(
            select(MatchOffer).where(MatchOffer.recipient_organization_id == actor.organization_id),
            MatchOffer,
            limit,
            cursor,
            session,
        )
        return OfferPage(
            items=[
                OfferRead(recommendation=r.recommendation, status=r.status, version=r.version)
                for r in rows
            ],
            next_cursor=next_cursor,
        )


@router.get("/matches/{identifier}", response_model=OfferRead)
def get_offer(identifier: UUID, request: Request, actor: Identity):
    require_role(actor, "recipient")
    with session_factory(request.app.state.settings.database_url)() as session:
        row = session.get(MatchOffer, identifier)
        if row is None or row.recipient_organization_id != actor.organization_id:
            raise AppError("not_found", "Not found.", 404)
        return OfferRead(recommendation=row.recommendation, status=row.status, version=row.version)


@router.get("/pickups", response_model=PickupPage)
def pickups(request: Request, actor: Identity, limit: Limit = 25, cursor: str | None = None):
    require_role(actor, "driver")
    with session_factory(request.app.state.settings.database_url)() as session:
        query = (
            select(Assignment)
            .join(Driver, Driver.id == Assignment.driver_id)
            .where(Driver.user_id == actor.user_id, Driver.organization_id == actor.organization_id)
        )
        rows, next_cursor = page_query(query, Assignment, limit, cursor, session)
        service = reservation(request)
        return PickupPage(
            items=[
                service.pickup_view(
                    r, session.get(Donation, r.donation_id), request.app.state.clock()
                )
                for r in rows
            ],
            next_cursor=next_cursor,
        )


@router.get("/operations/failures", response_model=FailurePage)
def failures(request: Request, actor: Identity, limit: Limit = 25, cursor: str | None = None):
    require_role(actor, "operator")
    with session_factory(request.app.state.settings.database_url)() as session:
        query = (
            select(TaskFailure)
            .join(Donation, Donation.id == TaskFailure.donation_id)
            .where(Donation.donor_organization_id == actor.organization_id)
        )
        rows, next_cursor = page_query(query, TaskFailure, limit, cursor, session)
        return FailurePage(
            items=[
                FailureRead(
                    id=r.id,
                    donation_id=r.donation_id,
                    step_id=r.step_id,
                    code=r.code,
                    attempts=r.attempts,
                    created_at=r.created_at,
                    replay_count=r.replay_count,
                )
                for r in rows
            ],
            next_cursor=next_cursor,
        )


@router.post(
    "/operations/failures/{identifier}/replay", response_model=ReplayResult, status_code=202
)
def replay(identifier: UUID, body: VersionCommand, request: Request, actor: Identity, key: Key):
    return coordinator(request).replay(actor, identifier, body, key)


@router.get("/operations/summary", response_model=OperationsSummary)
def summary(request: Request, actor: Identity):
    require_role(actor, "operator")
    with session_factory(request.app.state.settings.database_url)() as session:
        counts = dict(
            session.execute(
                select(Donation.status, func.count())
                .where(Donation.donor_organization_id == actor.organization_id)
                .group_by(Donation.status)
            ).all()
        )
        kg, count = session.execute(
            select(func.coalesce(func.sum(Impact.quantity_kg), 0), func.count())
            .join(Donation, Donation.id == Impact.donation_id)
            .where(Donation.donor_organization_id == actor.organization_id)
        ).one()
        return OperationsSummary(
            organization_id=actor.organization_id,
            counts_by_status=counts,
            notification_counts_by_status=dict(
                session.execute(
                    select(Notification.status, func.count())
                    .join(Donation, Donation.id == Notification.donation_id)
                    .where(Donation.donor_organization_id == actor.organization_id)
                    .group_by(Notification.status)
                ).all()
            ),
            delivered_kg=float(kg),
            delivered_count=count,
            synthetic=request.app.state.settings.enable_local_workflow_demo
            or bool(
                session.scalar(
                    select(
                        exists().where(
                            IntakeEvaluation.donation_id == Donation.id,
                            Donation.donor_organization_id == actor.organization_id,
                            IntakeEvaluation.batch["synthetic"].as_boolean().is_(True),
                        )
                    )
                )
            ),
        )


@router.get("/events", response_class=StreamingResponse)
async def events(
    request: Request,
    actor: Identity,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    service = StreamService(request.app.state.settings.database_url, request.app.state.clock)
    cursor = await asyncio.to_thread(service.cursor, last_event_id)

    async def stream():
        nonlocal cursor
        heartbeat = time.monotonic()
        while not await request.is_disconnected():
            try:
                # Revalidate token expiry and membership throughout a long-lived connection.
                current = await asyncio.to_thread(current_actor, request, None)
                if current != actor:
                    return
                rows = await asyncio.to_thread(service.read, actor, cursor)
            except AppError:
                return
            for item in rows:
                cursor = item["sequence"]
                data = json.dumps(item["event"], separators=(",", ":"))
                yield f"id: {cursor}\nevent: status\ndata: {data}\n\n"
            if time.monotonic() - heartbeat >= 15:
                yield ": keepalive\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
