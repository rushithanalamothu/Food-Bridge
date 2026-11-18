"""Authorized role-application snapshots and receiving-profile maintenance."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import select

from foodbridge.agents.reservation.service import ReservationService
from foodbridge.api.routes.workflow import Identity, page_query
from foodbridge.applications.service import ApplicationService
from foodbridge.auth.workflow import membership_choices
from foodbridge.db.models import Donation
from foodbridge.db.workflow import require_role, snapshot
from foodbridge.db.workflow_models import Reservation
from foodbridge.domain.errors import AppError
from foodbridge.domain.workflow import (
    DonationBoard,
    DonationDetail,
    DriverOriginRead,
    DriverOriginUpdate,
    MembershipRead,
    ReceivingProfileRead,
    ReceivingProfileUpdate,
    ReservationDetail,
    ReservationPage,
)

router = APIRouter(prefix="/api/v1", tags=["applications"])
Key = Annotated[UUID, Header(alias="Idempotency-Key")]
Limit = Annotated[int, Query(ge=1, le=100)]


def service(request):
    return ApplicationService(request.app.state.settings.database_url, request.app.state.clock)


@router.get("/workflow/donations", response_model=DonationBoard)
def board(
    request: Request,
    actor: Identity,
    limit: Limit = 25,
    cursor: str | None = None,
    order: Literal["oldest", "newest"] = "newest",
):
    app = service(request)
    with app.sessions() as session:
        rows, following = page_query(
            select(Donation).where(app.scope(actor)), Donation, limit, cursor, session, order
        )
        return DonationBoard(
            items=[snapshot(row, app.clock()) for row in rows], next_cursor=following
        )


@router.get("/workflow/donations/{identifier}", response_model=DonationDetail)
def detail(identifier: UUID, request: Request, actor: Identity):
    return service(request).detail(actor, identifier)


@router.get("/receiving-profile", response_model=ReceivingProfileRead)
def profile(request: Request, actor: Identity):
    return service(request).profile(actor)


@router.post("/receiving-profile", response_model=ReceivingProfileRead)
def update_profile(body: ReceivingProfileUpdate, request: Request, actor: Identity, key: Key):
    return service(request).update_profile(actor, body, key, request.state.request_id)


@router.post("/driver-origin", response_model=DriverOriginRead)
def update_driver_origin(body: DriverOriginUpdate, request: Request, actor: Identity, key: Key):
    return service(request).update_driver_origin(actor, body, key, request.state.request_id)


@router.get("/driver-origin", response_model=DriverOriginRead)
def driver_origin(request: Request, actor: Identity):
    return service(request).driver_origin(actor)


@router.get("/reservations", response_model=ReservationPage)
def reservations(
    request: Request,
    actor: Identity,
    limit: Limit = 25,
    cursor: str | None = None,
    order: Literal["oldest", "newest"] = "newest",
):
    require_role(actor, "recipient")
    app = service(request)
    with app.sessions() as session:
        rows, following = page_query(
            select(Reservation).where(
                Reservation.recipient_organization_id == actor.organization_id
            ),
            Reservation,
            limit,
            cursor,
            session,
            order,
        )
        return ReservationPage(
            items=[
                ReservationDetail(
                    reservation=ReservationService.reservation_view(
                        row, session.get(Donation, row.donation_id)
                    ),
                    donation=snapshot(session.get(Donation, row.donation_id), app.clock()),
                )
                for row in rows
            ],
            next_cursor=following,
        )


@router.get("/reservations/{identifier}", response_model=ReservationDetail)
def reservation_detail(identifier: UUID, request: Request, actor: Identity):
    require_role(actor, "recipient")
    app = service(request)
    with app.sessions() as session:
        row = session.get(Reservation, identifier)
        if row is None or row.recipient_organization_id != actor.organization_id:
            raise AppError("not_found", "Reservation not found.", 404)
        donation = session.get(Donation, row.donation_id)
        return ReservationDetail(
            reservation=ReservationService.reservation_view(row, donation),
            donation=snapshot(donation, app.clock()),
        )


@router.get("/memberships", response_model=list[MembershipRead])
def memberships(request: Request):
    return membership_choices(request)
