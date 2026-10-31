"""Legal aggregate transitions, independent of frameworks and persistence.

Permissions, eligibility and optimistic version checks must ALSO pass in the transaction.
"""

from enum import StrEnum


class DonationStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    NEEDS_REVIEW = "needs_review"
    MATCHING = "matching"
    OFFERED = "offered"
    RESERVED = "reserved"
    PICKUP_ASSIGNED = "pickup_assigned"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    NO_MATCH = "no_match"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


S = DonationStatus
TRANSITIONS: dict[DonationStatus, frozenset[DonationStatus]] = {
    S.DRAFT: frozenset({S.SUBMITTED, S.CANCELLED}),
    S.SUBMITTED: frozenset({S.NEEDS_REVIEW, S.MATCHING, S.EXPIRED, S.CANCELLED, S.FAILED}),
    S.NEEDS_REVIEW: frozenset({S.SUBMITTED, S.EXPIRED, S.CANCELLED}),
    S.MATCHING: frozenset({S.OFFERED, S.NO_MATCH, S.EXPIRED, S.CANCELLED, S.FAILED}),
    S.OFFERED: frozenset({S.RESERVED, S.MATCHING, S.EXPIRED, S.CANCELLED, S.FAILED}),
    S.RESERVED: frozenset({S.PICKUP_ASSIGNED, S.MATCHING, S.EXPIRED, S.CANCELLED, S.FAILED}),
    S.PICKUP_ASSIGNED: frozenset({S.PICKED_UP, S.RESERVED, S.EXPIRED, S.CANCELLED, S.FAILED}),
    S.PICKED_UP: frozenset({S.DELIVERED, S.FAILED}),
    S.DELIVERED: frozenset(),
    S.NO_MATCH: frozenset(),
    S.EXPIRED: frozenset(),
    S.CANCELLED: frozenset(),
    S.FAILED: frozenset(),
}


def assert_transition(current: DonationStatus, target: DonationStatus) -> None:
    if target not in TRANSITIONS[current]:
        raise ValueError(f"Invalid donation transition: {current} -> {target}")
