"""Bounded OSRM-compatible road routes. Unavailable routes never become road ETAs."""

import math

import httpx

from foodbridge.domain.contracts import Location
from foodbridge.integrations.ports import RouteEstimate
from foodbridge.integrations.workflow import DependencyUnavailable


class NoRoute(Exception):
    """The provider found no drivable path for this pair."""


class OSRMRouting:
    def __init__(self, base_url: str, timeout_s: float = 8, transport=None):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.transport = transport

    def estimate(self, origin: Location, destination: Location) -> RouteEstimate:
        coordinates = (
            f"{origin.longitude},{origin.latitude};{destination.longitude},{destination.latitude}"
        )
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
                response = client.get(
                    f"{self.base_url}/route/v1/driving/{coordinates}",
                    params={"overview": "false", "steps": "false"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
            raise DependencyUnavailable("routing_service_unavailable") from None
        if not isinstance(payload, dict):
            raise DependencyUnavailable("routing_service_unavailable")
        if payload.get("code") == "NoRoute":
            raise NoRoute
        routes = payload.get("routes")
        if payload.get("code") != "Ok" or not isinstance(routes, list) or not routes:
            raise DependencyUnavailable("routing_service_unavailable")
        try:
            distance = float(routes[0]["distance"])
            duration = float(routes[0]["duration"])
            if not all(math.isfinite(v) and v >= 0 for v in (distance, duration)):
                raise ValueError
            return RouteEstimate(
                distance_m=distance, travel_time_s=duration, provider="osrm", estimated=False
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise DependencyUnavailable("routing_service_unavailable") from None


class FakeRouting:
    """Explicit synthetic routes for deterministic tests and evaluation only."""

    def __init__(self, routes: dict[tuple[float, float, float, float], tuple[float, float]]):
        self.routes = routes

    def estimate(self, origin: Location, destination: Location) -> RouteEstimate:
        key = (origin.latitude, origin.longitude, destination.latitude, destination.longitude)
        if key not in self.routes:
            raise NoRoute
        distance, duration = self.routes[key]
        return RouteEstimate(
            distance_m=distance, travel_time_s=duration, provider="synthetic", estimated=False
        )
