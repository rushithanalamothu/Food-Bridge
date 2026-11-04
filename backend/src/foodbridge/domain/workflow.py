"""Versioned workflow commands and read models. No infrastructure dependencies."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from foodbridge.domain.contracts import Contract, DonationRead, EventEnvelope, MatchRecommendation

Role = Literal["donor", "recipient", "driver", "operator"]


class Actor(Contract):
    user_id: UUID
    organization_id: UUID
    role: Role


class VersionCommand(Contract):
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=200)


class DonationCommand(Contract):
    expected_donation_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=200)


class PickupConfirmation(VersionCommand):
    handling_confirmed: Literal[True]
    observed_quantity_kg: float = Field(gt=0, allow_inf_nan=False)


class DeliveryConfirmation(VersionCommand):
    delivery_confirmed: Literal[True]


class ReservationRead(Contract):
    id: UUID
    donation_id: UUID
    match_id: UUID
    recipient_organization_id: UUID
    quantity_kg: float
    storage: str
    status: Literal["active", "released", "completed", "failed"]
    version: int
    donation_version: int
    created_at: AwareDatetime


class PickupRead(Contract):
    id: UUID
    donation_id: UUID
    reservation_id: UUID
    driver_id: UUID
    status: Literal[
        "assigned", "accepted", "declined", "collected", "delivered", "released", "failed"
    ]
    version: int
    start: AwareDatetime
    end: AwareDatetime
    donation: DonationRead


class PickupPage(Contract):
    items: list[PickupRead]
    next_cursor: str | None = None


class OfferRead(Contract):
    recommendation: MatchRecommendation
    status: Literal["offered", "accepted", "declined", "expired", "superseded"]
    version: int


class OfferPage(Contract):
    items: list[OfferRead]
    next_cursor: str | None = None


class FailureRead(Contract):
    id: UUID
    donation_id: UUID
    step_id: UUID
    code: str
    attempts: int
    created_at: AwareDatetime
    replay_count: int


class FailurePage(Contract):
    items: list[FailureRead]
    next_cursor: str | None = None


class ReplayResult(Contract):
    failure_id: UUID
    step_id: UUID
    status: Literal["queued"] = "queued"


class OperationsSummary(Contract):
    organization_id: UUID
    counts_by_status: dict[str, int]
    notification_counts_by_status: dict[str, int] = Field(default_factory=dict)
    delivered_kg: float
    delivered_count: int
    synthetic: bool


class StreamItem(Contract):
    sequence: int
    event: EventEnvelope


class WorkflowContracts(Contract):
    actor: Actor
    version_command: VersionCommand
    donation_command: DonationCommand
    pickup_confirmation: PickupConfirmation
    delivery_confirmation: DeliveryConfirmation
    reservation: ReservationRead
    pickup: PickupRead
    pickups: PickupPage
    offer: OfferRead
    offers: OfferPage
    failure: FailureRead
    failures: FailurePage
    replay: ReplayResult
    summary: OperationsSummary
    stream_item: StreamItem
