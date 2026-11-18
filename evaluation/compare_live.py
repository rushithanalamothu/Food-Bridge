"""Validate and compare two separately captured local full-stack benchmark runs."""

import argparse
import json
from pathlib import Path


def compare(distance, multi):
    first, second = distance["manifest"], multi["manifest"]
    if first["strategy"] != "distance_only" or second["strategy"] != "multi_criteria":
        raise ValueError("Pass the distance-only run first and the multi-criteria run second")
    for key in (
        "count",
        "build_sha",
        "fixture",
        "ranking_config_sha256",
        "intake_policy_sha256",
    ):
        if first[key] != second[key]:
            raise ValueError(f"Benchmarks have different {key}")
    if not first["routing_map"] or first["routing_map"] != second["routing_map"]:
        raise ValueError("Benchmarks used different or unrecorded road-network data")
    if not first["compose_project"] or first["compose_project"] == second["compose_project"]:
        raise ValueError("Strategies must run in separate Compose databases")
    if distance["error"] or multi["error"]:
        raise ValueError("One or both runs failed; inspect raw records")
    if any(len(item["records"]) != first["count"] for item in (distance, multi)):
        raise ValueError("Both runs must complete the full workload")
    keys = (
        "delivered_under_local_script",
        "server_recorded_offer_p50_ms",
        "server_recorded_offer_p95_ms",
        "client_observed_offer_p95_ms",
        "allocation_kg_by_fixture_recipient",
        "fairness_jain_across_fixture_recipients",
    )
    return {
        "scope": "local synthetic full-stack demonstration, serial arrivals and scripted delivery",
        "same_build_config_and_map": True,
        "distinct_compose_databases": [first["compose_project"], second["compose_project"]],
        "count_per_strategy": first["count"],
        "distance_only": {key: distance["summary"][key] for key in keys},
        "multi_criteria": {key: multi["summary"][key] for key in keys},
        "limitations": (
            "These are local serial synthetic actors and forced acceptance/delivery; "
            "no production pickup-rate or concurrent-traffic claim is supported."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("distance_only", type=Path)
    parser.add_argument("multi_criteria", type=Path)
    args = parser.parse_args()
    result = compare(
        json.loads(args.distance_only.read_text()), json.loads(args.multi_criteria.read_text())
    )
    print(json.dumps(result, indent=2, sort_keys=True))
