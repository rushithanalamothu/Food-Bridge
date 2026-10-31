from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from foodbridge.agents.intake.demo import demo_batch
from foodbridge.agents.intake.policy import evaluate, urgency, validate_confirmation
from foodbridge.domain.contracts import DonationInput, DonationRead
from foodbridge.domain.intake import EligibilityBatch, IntakeDonationRead

NOW = datetime(2026, 10, 30, 22, tzinfo=UTC)
EXAMPLE = Path(__file__).resolve().parents[3] / "contracts/examples/donation-input.json"


@pytest.fixture
def food():
    return DonationInput.model_validate_json(EXAMPLE.read_text())


@pytest.fixture
def batch(food):
    row = DonationRead(
        **food.model_dump(),
        id=uuid4(),
        donor_organization_id=uuid4(),
        status="submitted",
        version=1,
        created_at=NOW,
    )
    return demo_batch(IntakeDonationRead(donation=row, urgency=urgency(food, NOW)), NOW)


def test_capacity_is_per_storage_and_exact_capacity_is_allowed(food, batch):
    result = evaluate(food, batch, NOW)
    assert result.decisions[0].eligible
    assert not result.decisions[1].eligible
    assert "insufficient_capacity" in result.decisions[1].reasons
    value = batch.model_dump(mode="json")
    value["candidates"][0]["recipient"]["available_capacity_kg_by_storage"] = {
        "ambient": 1000,
        "chilled": 9,
    }
    assert (
        "insufficient_capacity"
        in evaluate(food, EligibilityBatch.model_validate(value), NOW).decisions[0].reasons
    )
    value["candidates"][0]["recipient"]["available_capacity_kg_by_storage"]["chilled"] = 10
    assert evaluate(food, EligibilityBatch.model_validate(value), NOW).decisions[0].eligible


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("active_and_verified",), False, "recipient_unverified"),
        (("recipient", "accepted_categories"), ["bakery"], "category_not_accepted"),
        (("recipient", "rejected_allergens"), ["soya"], "allergen_conflict"),
        (("recipient", "required_dietary_tags"), ["vegan"], "dietary_mismatch"),
        (("route",), None, "route_unavailable"),
        (("route", "estimated"), True, "route_unverified"),
        (("route", "calculated_at"), (NOW - timedelta(seconds=301)).isoformat(), "route_stale"),
        (("route", "calculated_at"), (NOW + timedelta(seconds=31)).isoformat(), "route_stale"),
        (("driver",), None, "driver_unavailable"),
        (("driver", "available"), False, "driver_unavailable"),
        (("driver", "capacity_kg"), 9, "driver_capacity_or_storage"),
        (("driver", "storage_types"), ["ambient"], "driver_capacity_or_storage"),
        (
            ("driver", "window", "end"),
            (NOW + timedelta(minutes=30)).isoformat(),
            "driver_window_missed",
        ),
        (("route", "travel_time_s"), 6 * 3600, "safe_use_deadline_missed"),
    ],
)
def test_hard_constraint_cannot_be_bypassed(food, batch, path, value, reason):
    values = batch.model_dump(mode="json")
    obj = values["candidates"][0]
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value
    result = evaluate(food, EligibilityBatch.model_validate(values), NOW)
    assert reason in result.decisions[0].reasons
    assert not result.decisions[0].eligible


def test_live_evaluation_rejects_synthetic_routes(food, batch):
    batch.synthetic = False
    assert "route_unverified" in evaluate(food, batch, NOW).decisions[0].reasons


def test_expired_donation_cannot_pass_an_otherwise_valid_candidate(food, batch):
    assert "donation_expired" in evaluate(food, batch, food.safe_use_by).decisions[0].reasons


def test_receiving_window_wait_is_accounted_for(food, batch):
    batch.candidates[0].recipient.receiving_window.start = NOW + timedelta(hours=2)
    decision = evaluate(food, batch, NOW).decisions[0]
    assert decision.eligible
    assert decision.arrival_at == NOW + timedelta(hours=2)


def test_closed_recipient_is_rejected(food, batch):
    batch.candidates[0].recipient.receiving_window.end = NOW + timedelta(minutes=30)
    assert "recipient_closed" in evaluate(food, batch, NOW).decisions[0].reasons


def test_urgency_uses_confirmed_deadline_and_injected_clock(food):
    original = food.safe_use_by
    assert urgency(food, food.pickup_window.end - timedelta(seconds=3600)).priority == "critical"
    assert urgency(food, food.pickup_window.end).priority == "expired"
    assert urgency(food, NOW).basis == "confirmed_deadline"
    assert food.safe_use_by == original
    with pytest.raises(ValueError):
        urgency(food, datetime(2026, 10, 30))


@pytest.mark.parametrize("quantity", [0.0001, 10.0001, 1e12])
def test_confirmation_rejects_unstorable_weight_precision(food, quantity):
    food.quantity_kg = quantity
    with pytest.raises(ValueError):
        validate_confirmation(food, NOW)


def test_confirmed_unknown_allergens_are_rejected(food):
    food.allergens = ["not sure"]
    with pytest.raises(ValueError, match="allergens_need_review"):
        validate_confirmation(food, NOW)


@pytest.mark.parametrize("allergens", [["may contain soy"], ["unknown"], ["unlisted ingredient"]])
def test_unrecognized_allergen_text_requires_review(food, allergens):
    food.allergens = allergens
    with pytest.raises(ValueError, match="allergens_need_review"):
        validate_confirmation(food, NOW)


def test_conflicting_dietary_claims_are_rejected(food, batch):
    food.dietary_tags = ["gluten-free"]
    food.allergens = ["wheat"]
    with pytest.raises(ValueError, match="conflicting_dietary_claims"):
        validate_confirmation(food, NOW)
    assert "conflicting_dietary_claims" in evaluate(food, batch, NOW).decisions[0].reasons


def test_configured_urgency_thresholds_are_used_and_versioned(food):
    from foodbridge.domain.intake import IntakePolicy

    policy = IntakePolicy(version="test-policy", critical_window_s=20000, high_window_s=21000)
    result = urgency(food, NOW, policy)
    assert result.priority == "critical"
    assert result.policy_version == "test-policy"


@pytest.mark.parametrize(
    "remaining,priority",
    [
        (-1, "expired"),
        (0, "expired"),
        (1, "critical"),
        (7200, "critical"),
        (7201, "high"),
        (21600, "high"),
        (21601, "normal"),
    ],
)
def test_spec_v03_urgency_boundaries(food, remaining, priority):
    value = urgency(food, food.pickup_window.end - timedelta(seconds=remaining))
    assert value.priority == priority
    assert value.policy_version == "eligibility-v2"
    assert 0 <= value.score <= 1


def test_required_policy_cannot_remove_safety_fields():
    from pydantic import ValidationError

    from foodbridge.domain.intake import IntakePolicy

    with pytest.raises(ValidationError, match="mandatory safety fields"):
        IntakePolicy(required_fields=["food_name"])


def test_additional_required_field_blocks_confirmation_and_all_candidates(food, batch):
    from foodbridge.domain.intake import IntakePolicy

    policy = IntakePolicy()
    policy.required_fields.append("packaging_type")
    with pytest.raises(ValueError, match="required_detail_missing"):
        validate_confirmation(food, NOW, policy)
    result = evaluate(food, batch, NOW, policy)
    assert result.donation_decision == "needs_review"
    assert result.donation_reasons == ["required_detail_missing"]
    assert all(not item.eligible for item in result.decisions)
    food.packaging_type = "boxed"
    assert evaluate(food, batch, NOW, policy).donation_decision == "eligible"


def test_duplicate_recipient_ids_are_rejected_before_handoff(batch):
    from pydantic import ValidationError

    value = batch.model_dump()
    value["candidates"].append(value["candidates"][0])
    with pytest.raises(ValidationError, match="must be unique"):
        EligibilityBatch.model_validate(value)


def test_arrival_at_exact_safe_use_deadline_is_rejected(food, batch):
    from foodbridge.domain.intake import IntakePolicy

    # Both candidate pickup and arrival are future, but arrival is exactly expiry.
    candidate = batch.candidates[0]
    candidate.route.travel_time_s = 3600
    candidate.recipient.receiving_window.end = food.safe_use_by
    candidate.driver.window.end = food.safe_use_by
    food.pickup_window.start = food.safe_use_by - timedelta(seconds=3600 + 900)
    food.pickup_window.end = food.safe_use_by - timedelta(seconds=1)
    decision = evaluate(food, batch, NOW, IntakePolicy()).decisions[0]
    assert decision.arrival_at == food.safe_use_by
    assert not decision.eligible
    assert "safe_use_deadline_missed" in decision.reasons
