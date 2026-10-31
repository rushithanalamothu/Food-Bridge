"""Canonical v1 wire models. Edit here, then run `make contracts`. No ORM imports."""

from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from foodbridge.domain.states import DonationStatus

PositiveKg = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonNegativeKg = Annotated[float, Field(ge=0, allow_inf_nan=False)]
FoodCategory = Literal["prepared_meals", "produce", "bakery", "dairy", "pantry", "other"]
Storage = Literal["ambient", "chilled", "frozen"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Location(Contract):
    address: str = Field(min_length=1, max_length=500)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    timezone: str = Field(default="America/Los_Angeles", min_length=1)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class PickupWindow(Contract):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("pickup end must be after start")
        return self


class DonationInput(Contract):
    """Donor-confirmed data, not unreviewed LLM extraction."""

    description: str = Field(min_length=1, max_length=4000)
    food_name: str = Field(min_length=1, max_length=200)
    category: FoodCategory
    quantity_kg: PositiveKg
    portions: int | None = Field(default=None, gt=0)
    storage: Storage
    dietary_tags: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(description="Explicitly confirmed; [] means none declared.")
    pickup_location: Location
    pickup_window: PickupWindow
    safe_use_by: AwareDatetime
    handling_notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def before_deadline(self) -> Self:
        if self.pickup_window.end > self.safe_use_by:
            raise ValueError("pickup window must end by safe_use_by")
        return self


class DonationRead(DonationInput):
    id: UUID
    donor_organization_id: UUID
    status: DonationStatus
    version: int = Field(ge=1)
    created_at: AwareDatetime


class RecipientProfile(Contract):
    organization_id: UUID
    location: Location
    accepted_categories: list[FoodCategory] = Field(min_length=1)
    accepted_storage: list[Storage] = Field(min_length=1)
    available_capacity_kg_by_storage: dict[Storage, NonNegativeKg] = Field(min_length=1)
    rejected_allergens: list[str]
    required_dietary_tags: list[str] = Field(default_factory=list)
    receiving_window: PickupWindow
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def capacity_for_accepted_storage(self) -> Self:
        if set(self.accepted_storage) != set(self.available_capacity_kg_by_storage):
            raise ValueError("capacity must be specified for every accepted storage type")
        return self


class MatchRecommendation(Contract):
    id: UUID
    donation_id: UUID
    recipient_organization_id: UUID
    matching_round: int = Field(ge=1)
    donation_version: int = Field(ge=1)
    distance_m: float = Field(ge=0, allow_inf_nan=False)
    travel_time_s: float = Field(ge=0, allow_inf_nan=False)
    offer_expires_at: AwareDatetime
    explanation: str = Field(min_length=1, max_length=2000)
    algorithm: Literal["distance_only", "multi_criteria"]
    eligibility_policy_version: str = Field(min_length=1)
    ranking_config_version: str = Field(min_length=1)


class ReservationRequest(Contract):
    match_id: UUID
    expected_donation_version: int = Field(ge=1)


class EventEnvelope(Contract):
    """Queue metadata; payloads are IDs, never raw donor text or unrestricted PII."""

    event_id: UUID
    event_type: str = Field(pattern=r"^[a-z_]+\.[a-z_]+\.v1$")
    schema_version: Literal[1] = 1
    aggregate_id: UUID
    aggregate_version: int = Field(ge=1)
    correlation_id: UUID
    occurred_at: AwareDatetime
    payload: dict[str, str | int | bool | None]


class ApiError(Contract):
    code: str
    message: str
    request_id: UUID
    details: dict[str, str] = Field(default_factory=dict)


class FoodBridgeContracts(Contract):
    """Schema export bundle only; this wrapper is NOT an HTTP request body."""

    donation_input: DonationInput
    donation: DonationRead
    recipient: RecipientProfile
    recommendation: MatchRecommendation
    reservation_request: ReservationRequest
    event: EventEnvelope
    error: ApiError
