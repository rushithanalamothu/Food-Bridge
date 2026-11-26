"""Versioned workflow commands and read models. No infrastructure dependencies."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from foodbridge.domain.contracts import (
    Contract,
    DonationRead,
    EventEnvelope,
    Location,
    MatchRecommendation,
    NonNegativeKg,
    RecipientProfile,
    Storage,
)
from foodbridge.domain.intake import RouteFacts
from foodbridge.domain.orchestration import OrchestrationAudit

Role = Literal["donor", "recipient", "driver", "operator"]


class Actor(Contract):
    user_id: UUID
    organization_id: UUID
    role: Role


class SessionMembership(Contract):
    organization_id: UUID
    organization_name: str
    role: Role


class BrowserSessionRead(Contract):
    authenticated: bool
    login_enabled: bool
    registration_enabled: bool = False
    mode: Literal["oidc", "local_demo"] | None = None
    memberships: list[SessionMembership]


class DriverOriginUpdate(Contract):
    expected_version: int = Field(ge=1)
    origin: Location


class DriverOriginRead(Contract):
    driver_id: UUID
    version: int
    origin: Location | None = None
    observed_at: AwareDatetime | None = None


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
    recipient_organization_id: UUID | None = None
    delivery_location: Location | None = None
    route: RouteFacts | None = None
    destination: Location | None = None
    recipient_name: str | None = None


class PickupPage(Contract):
    items: list[PickupRead]
    next_cursor: str | None = None


class OfferRead(Contract):
    recommendation: MatchRecommendation
    status: Literal["offered", "accepted", "declined", "expired", "superseded"]
    version: int
    donation: DonationRead | None = None
    requires_revalidation: bool = False


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


class MembershipRead(Contract):
    user_id: UUID
    organization_id: UUID
    organization_name: str
    role: Role


class DonationHistoryItem(Contract):
    aggregate_version: int
    previous_status: str | None
    next_status: str
    reason: str
    occurred_at: AwareDatetime


class DonationDetail(Contract):
    donation: DonationRead
    history: list[DonationHistoryItem]


class DonationBoard(Contract):
    items: list[DonationRead]
    next_cursor: str | None = None


class ReceivingProfileRead(Contract):
    profile: "RecipientProfile"
    reported_free_kg_by_storage: dict[str, float]
    committed_inbound_kg_by_storage: dict[str, float]
    capacity_versions: dict[str, int]
    verified: bool


class ReceivingProfileUpdate(Contract):
    expected_version: int = Field(ge=1)
    expected_capacity_versions: dict[str, int]
    profile: "RecipientProfile"
    reported_free_kg_by_storage: dict["Storage", "NonNegativeKg"]


class ReservationDetail(Contract):
    reservation: ReservationRead
    donation: DonationRead


class ReservationPage(Contract):
    items: list[ReservationDetail]
    next_cursor: str | None = None


class HistoryEntry(Contract):
    version: int
    previous_status: str | None
    status: str
    reason: str
    occurred_at: AwareDatetime


class HistoryPage(Contract):
    items: list[HistoryEntry]
    next_version: int | None = None


OperationsDonationPage = DonationBoard


class WorkflowContracts(Contract):
    orchestrator_audit: OrchestrationAudit
    browser_session: BrowserSessionRead
    operations_donations: DonationBoard
    history: HistoryPage
    actor: Actor
    driver_origin_update: DriverOriginUpdate
    driver_origin: DriverOriginRead
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
    memberships: list[MembershipRead]
    donation_detail: DonationDetail
    donation_board: DonationBoard
    receiving_profile: ReceivingProfileRead
    receiving_profile_update: ReceivingProfileUpdate
    reservation_detail: ReservationDetail
    reservation_page: ReservationPage
