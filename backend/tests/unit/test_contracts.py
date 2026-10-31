import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from foodbridge.domain.contracts import DonationInput, EventEnvelope

ROOT = Path(__file__).resolve().parents[3]


def donation():
    return json.loads((ROOT / "contracts/examples/donation-input.json").read_text())


def test_canonical_example_is_valid():
    assert DonationInput.model_validate(donation()).quantity_kg == 10


@pytest.mark.parametrize("quantity", [0, -1, float("nan"), float("inf")])
def test_quantity_must_be_finite_and_positive(quantity):
    value = donation()
    value["quantity_kg"] = quantity
    with pytest.raises(ValidationError):
        DonationInput.model_validate(value)


def test_naive_timestamps_are_rejected():
    value = donation()
    value["safe_use_by"] = "2026-10-31T03:00:00"
    with pytest.raises(ValidationError):
        DonationInput.model_validate(value)


def test_invalid_timezone_is_rejected():
    value = donation()
    value["pickup_location"]["timezone"] = "Mars/Olympus"
    with pytest.raises(ValidationError):
        DonationInput.model_validate(value)


def test_pickup_must_finish_before_deadline():
    value = donation()
    value["safe_use_by"] = value["pickup_window"]["start"]
    with pytest.raises(ValidationError):
        DonationInput.model_validate(value)


def test_unknown_allergens_are_not_silently_assumed_safe():
    value = donation()
    del value["allergens"]
    with pytest.raises(ValidationError):
        DonationInput.model_validate(value)
    value["allergens"] = []
    DonationInput.model_validate(value)


def test_browser_cannot_set_state_on_creation():
    value = donation()
    value["status"] = "reserved"
    with pytest.raises(ValidationError):
        DonationInput.model_validate(value)


def test_example_event_has_versioned_type():
    value = json.loads((ROOT / "contracts/examples/event.json").read_text())
    event = EventEnvelope.model_validate(value)
    assert event.schema_version == 1
    invalid = deepcopy(value)
    invalid["event_type"] = "donation.submitted"
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(invalid)


@pytest.mark.parametrize(
    ("model_name", "example"),
    [
        ("RecipientProfile", "recipient-profile.json"),
        ("MatchRecommendation", "match-recommendation.json"),
        ("ReservationRequest", "reservation-request.json"),
    ],
)
def test_handoff_examples_match_canonical_types(model_name, example):
    from foodbridge.domain import contracts

    value = json.loads((ROOT / "contracts/examples" / example).read_text())
    getattr(contracts, model_name).model_validate(value)


def test_capacity_cannot_be_pooled_across_storage_types():
    from foodbridge.domain.contracts import RecipientProfile

    value = json.loads((ROOT / "contracts/examples/recipient-profile.json").read_text())
    del value["available_capacity_kg_by_storage"]["chilled"]
    with pytest.raises(ValidationError):
        RecipientProfile.model_validate(value)
