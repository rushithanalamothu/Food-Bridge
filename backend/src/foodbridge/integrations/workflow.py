"""Ports for Rushitha's candidate/ranking work. Unconfigured production fails explicitly."""

from typing import Protocol
from uuid import UUID

from foodbridge.domain.contracts import DonationRead, MatchRecommendation
from foodbridge.domain.intake import EligibilityBatch, IntakeHandoff


class DependencyUnavailable(Exception):
    """Retryable; the message is a stable non-private reason, never a provider exception."""

    def __init__(self, code):
        allowed = {
            "matching_service_unavailable",
            "routing_service_unavailable",
            "notification_service_unavailable",
            "provider_failure",
        }
        self.code = code if code in allowed else "provider_failure"
        super().__init__(self.code)


class MatchingGateway(Protocol):
    def candidates(
        self, donation: DonationRead, excluded_recipients: set[UUID], excluded_drivers: set[UUID]
    ) -> EligibilityBatch: ...

    def rank(self, handoff: IntakeHandoff, matching_round: int) -> MatchRecommendation | None: ...


class UnconfiguredMatching:
    def candidates(self, donation, excluded_recipients, excluded_drivers):
        raise DependencyUnavailable("matching_service_unavailable")

    def rank(self, handoff, matching_round):
        raise DependencyUnavailable("matching_service_unavailable")


def matching_gateway(settings):
    if settings.enable_local_workflow_demo:
        from foodbridge.agents.orchestrator.demo import DemoMatching

        return DemoMatching(settings.database_url)
    return UnconfiguredMatching()
