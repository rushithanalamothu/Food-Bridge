"""Intake wire contracts. Proposals are never donor-confirmed donations."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from foodbridge.domain.contracts import (
    Contract,
    DonationInput,
    DonationRead,
    FoodCategory,
    Location,
    PickupWindow,
    PositiveKg,
    RecipientProfile,
    Storage,
)

NonNegativeNumber = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class IntakePolicy(Contract):
    version: str = Field(default="eligibility-v1", min_length=1)
    handling_buffer_s: int = Field(default=900, ge=0, le=86400)
    route_max_age_s: int = Field(default=300, gt=0, le=86400)
    critical_window_s: int = Field(default=3600, gt=0)
    high_window_s: int = Field(default=10800, gt=0)
    urgency_horizon_s: int = Field(default=21600, gt=0)

    @model_validator(mode="after")
    def ordered_windows(self) -> Self:
        if not self.critical_window_s <= self.high_window_s <= self.urgency_horizon_s:
            raise ValueError("urgency windows must be in increasing order")
        return self


class ProposedFields(Contract):
    food_name: str | None = Field(default=None, max_length=200)
    category: FoodCategory | None = None
    quantity_kg: PositiveKg | None = None
    portions: int | None = Field(default=None, gt=0)
    storage: Storage | None = None
    dietary_tags: list[str] | None = None
    allergens: list[str] | None = None
    pickup_window: PickupWindow | None = None
    safe_use_by: AwareDatetime | None = None
    handling_notes: str = Field(default="", max_length=1000)


class ReviewIssue(Contract):
    field: str
    code: Literal["missing", "uncertain", "provider_unavailable", "source_mismatch"]
    message: str


class ExtractionResult(Contract):
    fields: ProposedFields
    provider: Literal["rules", "openai", "gemini", "anthropic", "openai_compatible"]
    model: str | None = None
    prompt_version: str = "intake-extraction-v1"
    evidence: dict[str, str] = Field(default_factory=dict)
    issues: list[ReviewIssue] = Field(default_factory=list)


class DraftCreate(Contract):
    description: str = Field(min_length=1, max_length=4000)
    pickup_location: Location


class DraftRead(DraftCreate):
    id: UUID
    donor_organization_id: UUID
    version: int = Field(ge=1)
    status: Literal["review_required", "confirmed"]
    extraction: ExtractionResult
    created_at: AwareDatetime
    donation_id: UUID | None = None


class DonationSubmit(Contract):
    draft_id: UUID
    expected_draft_version: int = Field(ge=1)
    confirmed: Literal[True]
    donation: DonationInput


class UrgencyAssessment(Contract):
    priority: Literal["normal", "high", "critical", "expired"]
    deadline_at: AwareDatetime
    seconds_remaining: float
    score: float = Field(ge=0, le=1)
    policy_version: str = "eligibility-v1"
    basis: Literal["confirmed_deadline"] = "confirmed_deadline"


class IntakeDonationRead(Contract):
    donation: DonationRead
    urgency: UrgencyAssessment
    handoff: Literal["awaiting_orchestrator"] = "awaiting_orchestrator"


class DonationPage(Contract):
    items: list[IntakeDonationRead]
    next_cursor: str | None


class DonorIdentity(Contract):
    user_id: UUID
    organization_id: UUID
    organization_name: str
    display_name: str
    pickup_location: Location
    mode: Literal["local_demo", "oidc"]


class RouteFacts(Contract):
    distance_m: NonNegativeNumber
    travel_time_s: NonNegativeNumber
    calculated_at: AwareDatetime
    source: Literal["routing_provider", "synthetic"]
    estimated: bool = False


class DriverFacts(Contract):
    id: UUID
    available: bool
    window: PickupWindow
    capacity_kg: PositiveKg
    storage_types: list[Storage] = Field(min_length=1)
    to_pickup_time_s: NonNegativeNumber


class EligibilityCandidate(Contract):
    recipient: RecipientProfile
    active_and_verified: bool
    route: RouteFacts | None
    driver: DriverFacts | None


class EligibilityBatch(Contract):
    donation_id: UUID
    expected_donation_version: int = Field(ge=1)
    candidates: list[EligibilityCandidate] = Field(max_length=100)
    synthetic: bool = False


class EligibilityDecision(Contract):
    recipient_organization_id: UUID
    recipient_version: int
    eligible: bool
    reasons: list[str]
    pickup_at: AwareDatetime | None = None
    arrival_at: AwareDatetime | None = None
    slack_s: float | None = None


class EligibilityResult(Contract):
    donation_id: UUID
    donation_version: int
    evaluated_at: AwareDatetime
    policy_version: str = "eligibility-v1"
    synthetic: bool
    urgency: UrgencyAssessment
    decisions: list[EligibilityDecision]


class EvaluationRead(Contract):
    id: UUID
    donation_id: UUID
    status: Literal["pending", "completed", "stale", "failed"]
    synthetic: bool
    result: EligibilityResult | None = None
    failure_code: str | None = None


class IntakeContracts(Contract):
    draft_create: DraftCreate
    draft: DraftRead
    submission: DonationSubmit
    donation: IntakeDonationRead
    donation_page: DonationPage
    identity: DonorIdentity
    extraction: ExtractionResult
    eligibility_batch: EligibilityBatch
    eligibility_result: EligibilityResult
    evaluation: EvaluationRead
    policy: IntakePolicy
