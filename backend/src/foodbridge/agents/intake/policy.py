"""Deterministic, provider-independent eligibility. No DB, network or framework imports."""

from datetime import datetime, timedelta
from decimal import Decimal

from foodbridge.domain.contracts import DonationInput
from foodbridge.domain.intake import (
    EligibilityBatch,
    EligibilityDecision,
    EligibilityResult,
    IntakePolicy,
    UrgencyAssessment,
)

DEFAULT_POLICY = IntakePolicy()
ALIASES = {
    "soya": "soy",
    "soybean": "soy",
    "soybeans": "soy",
    "peanuts": "peanut",
    "groundnut": "peanut",
    "dairy": "milk",
    "eggs": "egg",
    "tree_nuts": "tree_nut",
    "almonds": "tree_nut",
    "almond": "tree_nut",
    "walnuts": "tree_nut",
    "cashews": "tree_nut",
    "soy_sauce": "soy",
    "sulphites": "sulfites",
}
UNKNOWN = {"unknown", "unsure", "not_sure", "not_known"}
ALLERGENS = {
    "milk",
    "egg",
    "fish",
    "shellfish",
    "tree_nut",
    "peanut",
    "wheat",
    "soy",
    "sesame",
    "gluten",
    "barley",
    "rye",
    "celery",
    "mustard",
    "lupin",
    "sulfites",
}
DIET_CONFLICTS = {
    "vegan": {"milk", "egg", "fish", "shellfish"},
    "gluten_free": {"gluten", "wheat", "barley", "rye"},
    "dairy_free": {"milk"},
}


def normalize(value: str) -> str:
    value = value.strip().lower().replace("-", "_").replace(" ", "_")
    return ALIASES.get(value, value)


def urgency(
    donation: DonationInput, now: datetime, policy: IntakePolicy = DEFAULT_POLICY
) -> UrgencyAssessment:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    deadline = min(donation.pickup_window.end, donation.safe_use_by)
    remaining = (deadline - now).total_seconds()
    priority = (
        "expired"
        if remaining <= 0
        else "critical"
        if remaining <= policy.critical_window_s
        else ("high" if remaining <= policy.high_window_s else "normal")
    )
    return UrgencyAssessment(
        priority=priority,
        deadline_at=deadline,
        seconds_remaining=remaining,
        score=max(0, min(1, 1 - remaining / policy.urgency_horizon_s)),
        policy_version=policy.version,
    )


def validate_confirmation(
    donation: DonationInput, now: datetime, policy: IntakePolicy = DEFAULT_POLICY
) -> None:
    """Semantic checks beyond the reusable schema; donor deadlines cannot be invented."""
    if len(donation.description) > policy.max_description_length:
        raise ValueError("description_too_long")
    for field in policy.required_fields:
        value = getattr(donation, field)
        if value is None or value == "":
            raise ValueError("required_detail_missing")
    if urgency(donation, now, policy).priority == "expired":
        raise ValueError("pickup_deadline_passed")
    amount = Decimal(str(donation.quantity_kg))
    if amount > Decimal("999999999.999") or amount != amount.quantize(Decimal("0.001")):
        raise ValueError("quantity_precision_or_range")
    if amount <= 0:
        raise ValueError("quantity_too_small")
    allergens = {normalize(value) for value in donation.allergens}
    if not allergens <= ALLERGENS:
        raise ValueError("allergens_need_review")
    if any(allergens & DIET_CONFLICTS.get(normalize(tag), set()) for tag in donation.dietary_tags):
        raise ValueError("conflicting_dietary_claims")
    if not donation.food_name.strip():
        raise ValueError("food_name_required")


def evaluate(
    donation: DonationInput,
    batch: EligibilityBatch,
    now: datetime,
    policy: IntakePolicy = DEFAULT_POLICY,
) -> EligibilityResult:
    assessment = urgency(donation, now, policy)
    donation_reasons = []
    try:
        validate_confirmation(donation, now, policy)
    except ValueError as error:
        donation_reasons.append(str(error))
    donation_decision = (
        "needs_review"
        if "required_detail_missing" in donation_reasons
        else "rejected"
        if donation_reasons
        else "eligible"
    )
    decisions = []
    for candidate in batch.candidates:
        recipient, route, driver = candidate.recipient, candidate.route, candidate.driver
        reasons = list(donation_reasons)
        if assessment.priority == "expired":
            reasons.append("donation_expired")
        if not candidate.active_and_verified:
            reasons.append("recipient_unverified")
        if donation.category not in recipient.accepted_categories:
            reasons.append("category_not_accepted")
        if donation.storage not in recipient.accepted_storage:
            reasons.append("storage_not_supported")
        if (
            recipient.available_capacity_kg_by_storage.get(donation.storage, 0)
            < donation.quantity_kg
        ):
            reasons.append("insufficient_capacity")
        allergens = {normalize(v) for v in donation.allergens}
        rejected = {normalize(v) for v in recipient.rejected_allergens}
        if not allergens <= ALLERGENS:
            reasons.append("allergens_unknown")
        if not rejected <= ALLERGENS:
            reasons.append("recipient_policy_uncertain")
        if allergens & rejected or (
            "gluten" in rejected and allergens & {"wheat", "barley", "rye"}
        ):
            reasons.append("allergen_conflict")
        tags = {normalize(v) for v in donation.dietary_tags}
        if any(allergens & DIET_CONFLICTS.get(tag, set()) for tag in tags):
            reasons.append("conflicting_dietary_claims")
        if "vegan" in tags:
            tags.add("vegetarian")
        if not {normalize(v) for v in recipient.required_dietary_tags} <= tags:
            reasons.append("dietary_mismatch")
        if route is None:
            reasons.append("route_unavailable")
        else:
            age = (now - route.calculated_at).total_seconds()
            if age > policy.route_max_age_s or age < -30:
                reasons.append("route_stale")
            if route.estimated or (route.source == "synthetic" and not batch.synthetic):
                reasons.append("route_unverified")
        if driver is None or not driver.available:
            reasons.append("driver_unavailable")
        elif (
            driver.capacity_kg < donation.quantity_kg
            or donation.storage not in driver.storage_types
        ):
            reasons.append("driver_capacity_or_storage")
        pickup = arrival = None
        slack = None
        if route is not None and driver is not None and driver.available:
            travel = timedelta(seconds=route.travel_time_s + policy.handling_buffer_s)
            pickup = max(
                max(now, driver.window.start) + timedelta(seconds=driver.to_pickup_time_s),
                donation.pickup_window.start,
                recipient.receiving_window.start - travel,
            )
            arrival = pickup + travel
            if pickup > donation.pickup_window.end:
                reasons.append("pickup_window_missed")
            if arrival > recipient.receiving_window.end:
                reasons.append("recipient_closed")
            if arrival > driver.window.end:
                reasons.append("driver_window_missed")
            if arrival >= donation.safe_use_by:
                reasons.append("safe_use_deadline_missed")
            slack = min(
                (donation.pickup_window.end - pickup).total_seconds(),
                (
                    min(donation.safe_use_by, recipient.receiving_window.end, driver.window.end)
                    - arrival
                ).total_seconds(),
            )
        decisions.append(
            EligibilityDecision(
                recipient_organization_id=recipient.organization_id,
                recipient_version=recipient.version,
                eligible=not reasons,
                reasons=reasons,
                pickup_at=pickup,
                arrival_at=arrival,
                slack_s=slack,
            )
        )
    return EligibilityResult(
        donation_id=batch.donation_id,
        donation_version=batch.expected_donation_version,
        evaluated_at=now,
        synthetic=batch.synthetic,
        urgency=assessment,
        policy_version=policy.version,
        decisions=decisions,
        donation_decision=donation_decision,
        donation_reasons=donation_reasons,
    )
