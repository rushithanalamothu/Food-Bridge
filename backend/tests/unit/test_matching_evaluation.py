"""Offline comparisons must replay identical inputs with isolated accounting."""

from datetime import UTC, datetime

from evaluation.compare import compare, jain, replay
from scripts.generate_synthetic import generate


def test_jain_all_zero_is_not_reported_as_perfect_fairness():
    assert jain([0, 0, 0]) is None
    assert jain([10, 10, 10]) == 1


def test_synthetic_replay_is_independent_and_does_not_claim_pickups():
    base = datetime(2026, 10, 30, 20, tzinfo=UTC)
    scenario = generate(2026, base)
    before = scenario["recipients"][0]["available_capacity_kg_by_storage"].copy()
    first = replay(scenario, "distance_only")
    replay(scenario, "multi_criteria")
    again = replay(scenario, "distance_only")
    assert first["records"] == again["records"]
    assert first["allocations_kg"] == again["allocations_kg"]
    assert scenario["recipients"][0]["available_capacity_kg_by_storage"] == before
    assert first["summary"]["selected"] + first["summary"]["no_match"] == 20
    result = compare(2026, base)
    assert result["manifest"]["completion"].startswith("not simulated")
    assert result["manifest"]["dataset_sha256"]
