"""Donor intake endpoints. The demo evaluation endpoint never accepts client recipient facts."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from foodbridge.agents.intake.demo import demo_batch
from foodbridge.agents.intake.relay import dispatch_pending
from foodbridge.agents.intake.service import IntakeService
from foodbridge.auth.identity import current_donor
from foodbridge.domain.errors import AppError
from foodbridge.domain.intake import (
    DonationPage,
    DonationSubmit,
    DonorIdentity,
    DraftCreate,
    DraftRead,
    EvaluationRead,
    IntakeDonationRead,
)
from foodbridge.integrations.extraction import extract

router = APIRouter(prefix="/api/v1", tags=["intake"])
Actor = Annotated[DonorIdentity, Depends(current_donor)]
Key = Annotated[UUID, Header(alias="Idempotency-Key")]


def service(request: Request) -> IntakeService:
    return IntakeService(
        request.app.state.settings.database_url,
        request.app.state.clock,
        allow_synthetic=request.app.state.settings.enable_local_intake_demo,
    )


@router.get("/me", response_model=DonorIdentity)
def me(actor: Actor) -> DonorIdentity:
    return actor


@router.post("/donation-drafts", response_model=DraftRead, status_code=201)
def create_draft(body: DraftCreate, request: Request, actor: Actor, key: Key) -> DraftRead:
    proposal = extract(
        body.description,
        body.pickup_location.timezone,
        request.app.state.clock(),
        request.app.state.settings,
    )
    return service(request).create_draft(actor, body, proposal, key)


@router.get("/donation-drafts/{identifier}", response_model=DraftRead)
def get_draft(identifier: UUID, request: Request, actor: Actor) -> DraftRead:
    return service(request).get_draft(actor, identifier)


@router.post("/donations", response_model=IntakeDonationRead, status_code=202)
def submit(body: DonationSubmit, request: Request, actor: Actor, key: Key) -> IntakeDonationRead:
    return service(request).submit(actor, body, key, request.state.request_id)


@router.get("/donations", response_model=DonationPage)
def list_donations(
    request: Request,
    actor: Actor,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
):
    return service(request).list_donations(actor, limit, cursor)


@router.get("/donations/{identifier}", response_model=IntakeDonationRead)
def get_donation(identifier: UUID, request: Request, actor: Actor) -> IntakeDonationRead:
    return service(request).get_donation(actor, identifier)


@router.post(
    "/donations/{identifier}/demo-eligibility", response_model=EvaluationRead, status_code=202
)
def demo_eligibility(identifier: UUID, request: Request, actor: Actor, key: Key) -> EvaluationRead:
    if not request.app.state.settings.enable_local_intake_demo or actor.mode != "local_demo":
        raise AppError("not_found", "Not found.", 404)
    intake = service(request)
    snapshot = intake.get_donation(actor, identifier)
    batch = demo_batch(snapshot, request.app.state.clock())
    # The request body is fixed by the server; route timestamps are not an idempotency input.
    # Use the existing pending/completed evaluation on a retry of this command key.
    result = intake.request_demo_evaluation(actor, batch, key, request.state.request_id)
    dispatch_pending(request.app.state.settings, limit=1, evaluation_id=result.id)
    return result


@router.get("/intake/evaluations/{identifier}", response_model=EvaluationRead)
def get_evaluation(identifier: UUID, request: Request, actor: Actor) -> EvaluationRead:
    return service(request).get_evaluation(actor, identifier)
