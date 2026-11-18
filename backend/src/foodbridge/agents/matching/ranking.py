"""Pure deterministic ranking over an already eligible cohort."""

from dataclasses import dataclass
from uuid import UUID

from foodbridge.agents.matching.config import MatchingConfig
from foodbridge.domain.intake import EligibilityCandidate, IntakeHandoff


@dataclass(frozen=True)
class RankedCandidate:
    candidate: EligibilityCandidate
    score: float
    features: dict[str, float]


def eligible_cohort(handoff: IntakeHandoff) -> list[EligibilityCandidate]:
    approved = {
        decision.recipient_organization_id: decision.recipient_version
        for decision in handoff.result.decisions
        if decision.eligible and decision.recipient_version >= 1
    }
    return [
        candidate
        for candidate in handoff.eligible_candidates
        if approved.get(candidate.recipient.organization_id) == candidate.recipient.version
        and candidate.route is not None
        and candidate.driver is not None
    ]


def distance_only(handoff: IntakeHandoff) -> RankedCandidate | None:
    cohort = eligible_cohort(handoff)
    if not cohort:
        return None
    candidate = min(cohort, key=lambda c: (c.route.distance_m, str(c.recipient.organization_id)))
    return RankedCandidate(
        candidate=candidate,
        score=1.0,
        features={"distance_m": candidate.route.distance_m},
    )


def multi_criteria(
    handoff: IntakeHandoff, config: MatchingConfig, allocated_kg: dict[UUID, float]
) -> list[RankedCandidate]:
    cohort = eligible_cohort(handoff)
    decisions = {d.recipient_organization_id: d for d in handoff.result.decisions}
    largest_allocation = max(
        (allocated_kg.get(c.recipient.organization_id, 0) for c in cohort), default=0
    )
    rows = []
    for candidate in cohort:
        recipient = candidate.recipient
        distance = candidate.route.distance_m
        available = recipient.available_capacity_kg_by_storage[handoff.donation.storage]
        slack = decisions[recipient.organization_id].slack_s or 0
        features = {
            "distance": max(0.0, 1 - distance / config.max_search_radius_m),
            "capacity": min(1.0, available / (2 * handoff.donation.quantity_kg)),
            "fairness": (
                1 - allocated_kg.get(recipient.organization_id, 0) / largest_allocation
                if largest_allocation
                else 1.0
            ),
            "slack": max(0.0, min(1.0, slack / config.slack_horizon_s)),
        }
        score = sum(config.weights[name] * value for name, value in features.items())
        rows.append(RankedCandidate(candidate=candidate, score=score, features=features))
    return sorted(
        rows,
        key=lambda row: (
            -row.score,
            row.candidate.route.travel_time_s,
            str(row.candidate.recipient.organization_id),
        ),
    )
