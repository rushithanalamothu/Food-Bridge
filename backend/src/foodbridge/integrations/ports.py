"""Provider interfaces. Adapters may not change domain state or waive eligibility rules."""

from typing import Protocol

from pydantic import BaseModel, Field

from foodbridge.domain.contracts import Location


class RouteEstimate(BaseModel):
    distance_m: float = Field(ge=0)
    travel_time_s: float = Field(ge=0)
    provider: str
    estimated: bool = False


class RoutingProvider(Protocol):
    def estimate(self, origin: Location, destination: Location) -> RouteEstimate: ...


class NotificationProvider(Protocol):
    def send(self, *, notification_id: str, destination_id: str, template: str) -> None: ...
