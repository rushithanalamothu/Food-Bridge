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
