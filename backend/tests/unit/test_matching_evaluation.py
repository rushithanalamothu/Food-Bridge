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


def test_road_comparison_fetches_one_shared_route_set_and_keeps_synthetic_outcomes():
    from foodbridge.integrations.ports import RouteEstimate

    class Router:
        def __init__(self):
            self.calls = []

        def estimate(self, origin, destination):
            self.calls.append((origin, destination))
            return RouteEstimate(
                distance_m=1500, travel_time_s=250, provider="osrm", estimated=False
            )

    router = Router()
    result = compare(2026, datetime(2026, 10, 30, 20, tzinfo=UTC), routing=router)
    assert result["manifest"]["routing"] == "osrm_local_road_routes"
    assert result["manifest"]["route_facts_sha256"]
    assert result["manifest"]["completion"].startswith("not simulated")
    assert len(router.calls) <= 7  # One donor origin, six recipients and one driver origin.
    assert all(row["summary"]["submitted"] == 20 for row in result["strategies"])


def test_road_comparison_does_not_offer_a_recipient_without_a_route():
    from foodbridge.agents.matching.routing import NoRoute
    from foodbridge.integrations.ports import RouteEstimate

    class Router:
        def estimate(self, origin, destination):
            if origin.longitude != -121.9:
                raise NoRoute
            return RouteEstimate(
                distance_m=1500, travel_time_s=240, provider="osrm", estimated=False
            )

    result = compare(2026, datetime(2026, 10, 30, 20, tzinfo=UTC), routing=Router())
    assert [row["summary"]["selected"] for row in result["strategies"]] == [0, 0]


def test_live_benchmark_summary_includes_unselected_recipient_in_fairness():
    from scripts.benchmark_matching import summarize
    from scripts.seed_matching_demo import recipient_id

    chosen = str(recipient_id(0))
    records = [
        {
            "recipient_organization_id": chosen,
            "quantity_kg": 1,
            "status": "delivered",
            "server_recorded_submission_to_offer_ms": value,
            "client_observed_submission_to_offer_ms": value + 5,
        }
        for value in (10, 20, 30)
    ]
    summary = summarize(records)
    assert summary["allocation_kg_by_fixture_recipient"][str(recipient_id(1))] == 0
    assert summary["fairness_jain_across_fixture_recipients"] == 0.5
    assert summary["server_recorded_offer_p50_ms"] == 20
    assert summary["server_recorded_offer_p95_ms"] == 30


def test_live_comparison_rejects_shared_database_and_map_drift():
    import pytest
    from evaluation.compare_live import compare as compare_live

    def result(strategy, project):
        manifest = {
            "strategy": strategy,
            "compose_project": project,
            "count": 1,
            "build_sha": "same",
            "fixture": "same",
            "ranking_config_sha256": "same",
            "intake_policy_sha256": "same",
            "routing_map": {"source_sha256": "same"},
        }
        return {
            "manifest": manifest,
            "error": None,
            "records": [{}],
            "summary": {
                key: 0
                for key in (
                    "delivered_under_local_script",
                    "server_recorded_offer_p50_ms",
                    "server_recorded_offer_p95_ms",
                    "client_observed_offer_p95_ms",
                    "allocation_kg_by_fixture_recipient",
                    "fairness_jain_across_fixture_recipients",
                )
            },
        }

    distance = result("distance_only", "first")
    multi = result("multi_criteria", "second")
    assert compare_live(distance, multi)["same_build_config_and_map"]
    multi["manifest"]["compose_project"] = "first"
    with pytest.raises(ValueError, match="separate Compose"):
        compare_live(distance, multi)
    multi["manifest"]["compose_project"] = "second"
    multi["manifest"]["routing_map"] = {"source_sha256": "changed"}
    with pytest.raises(ValueError, match="road-network"):
        compare_live(distance, multi)
