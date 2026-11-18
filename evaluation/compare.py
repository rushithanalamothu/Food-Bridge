"""Independent offline ranking replay; no pickup or production routing claims."""

import argparse
import hashlib
import json
import math
import platform
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter_ns
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from scripts.generate_synthetic import generate

from foodbridge.agents.intake.config import load_policy
from foodbridge.agents.intake.policy import evaluate
from foodbridge.agents.matching.config import load_matching_config
from foodbridge.agents.matching.ranking import distance_only, multi_criteria
from foodbridge.agents.matching.routing import NoRoute, OSRMRouting
from foodbridge.domain.contracts import DonationRead, PickupWindow, RecipientProfile
from foodbridge.domain.intake import (
    DriverFacts,
    EligibilityBatch,
    EligibilityCandidate,
    IntakeHandoff,
    RouteFacts,
)

ROOT = Path(__file__).resolve().parents[1]
DRIVER_ORIGIN = {
    "address": "Synthetic San Jose driver origin",
    "latitude": 37.333,
    "longitude": -121.9,
}


def synthetic_route(donor, recipient, at):
    """Deterministic fixture values; these are deliberately not road-provider results."""
    metres = 500 + int(
        90_000
        * math.hypot(donor.latitude - recipient.latitude, donor.longitude - recipient.longitude)
    )
    return RouteFacts(
        distance_m=metres, travel_time_s=metres / 8, calculated_at=at, source="synthetic"
    )


def jain(values):
    total = sum(values)
    return (total * total / (len(values) * sum(v * v for v in values))) if total else None


def road_routes(scenario: dict, routing):
    """Fetch one immutable route set before either strategy changes capacity."""
    routes, cache = {}, {}
    driver_origin = RecipientProfile.model_validate(scenario["recipients"][0]).location.model_copy(
        update=DRIVER_ORIGIN
    )
    start = perf_counter_ns()

    def estimate(origin, destination):
        key = (origin.latitude, origin.longitude, destination.latitude, destination.longitude)
        if key not in cache:
            try:
                route = routing.estimate(origin, destination)
                cache[key] = {"distance_m": route.distance_m, "travel_time_s": route.travel_time_s}
            except NoRoute:
                cache[key] = None
        return cache[key]

    for raw in scenario["donations"]:
        donation = DonationRead.model_validate(raw)
        routes[str(donation.id)] = {
            "driver": estimate(driver_origin, donation.pickup_location),
            "recipients": {
                str(recipient.organization_id): estimate(
                    donation.pickup_location, recipient.location
                )
                for recipient in (
                    RecipientProfile.model_validate(row) for row in scenario["recipients"]
                )
            },
        }
    return routes, (perf_counter_ns() - start) / 1_000_000


def replay(scenario: dict, strategy: str, routes=None):
    """Rebuild capacity and allocation ledgers per strategy, from the same input."""
    policy, config = load_policy(), load_matching_config()
    base = datetime.fromisoformat(scenario["metadata"]["base_time"])
    recipients = [RecipientProfile.model_validate(row) for row in scenario["recipients"]]
    capacities = {
        recipient.organization_id: dict(recipient.available_capacity_kg_by_storage)
        for recipient in recipients
    }
    allocations = {recipient.organization_id: 0.0 for recipient in recipients}
    records = []
    elapsed = []
    for index, raw in enumerate(scenario["donations"]):
        start = perf_counter_ns()
        donation = DonationRead.model_validate(raw)
        now = base + timedelta(minutes=index)
        candidates = []
        for recipient in recipients:
            current = recipient.model_copy(deep=True)
            current.available_capacity_kg_by_storage = capacities[current.organization_id].copy()
            driver = DriverFacts(
                id=UUID(scenario["drivers"][index % len(scenario["drivers"])]["id"]),
                available=True,
                window=PickupWindow(start=base, end=base + timedelta(hours=8)),
                capacity_kg=40,
                storage_types=["ambient", "chilled"],
                to_pickup_time_s=(
                    routes[str(donation.id)]["driver"]["travel_time_s"]
                    if routes is not None and routes[str(donation.id)]["driver"]
                    else 300
                ),
            )
            route = (
                synthetic_route(donation.pickup_location, current.location, now)
                if routes is None
                else routes[str(donation.id)]["recipients"][str(current.organization_id)]
            )
            candidates.append(
                EligibilityCandidate(
                    recipient=current,
                    active_and_verified=True,
                    driver=driver if routes is None or routes[str(donation.id)]["driver"] else None,
                    route=(
                        RouteFacts(
                            **route,
                            calculated_at=now,
                            source="routing_provider",
                        )
                        if routes is not None and route is not None
                        else route
                    ),
                )
            )
        batch = EligibilityBatch(
            donation_id=donation.id,
            expected_donation_version=donation.version,
            candidates=candidates,
            synthetic=True,
        )
        result = evaluate(donation, batch, now, policy)
        approved = {d.recipient_organization_id for d in result.decisions if d.eligible}
        handoff = IntakeHandoff(
            evaluation_id=uuid4(),
            donation=donation,
            result=result,
            eligible_candidates=[c for c in candidates if c.recipient.organization_id in approved],
        )
        ranked = (
            distance_only(handoff)
            if strategy == "distance_only"
            else next(iter(multi_criteria(handoff, config, allocations)), None)
        )
        chosen = ranked.candidate.recipient.organization_id if ranked else None
        if chosen:
            capacities[chosen][donation.storage] -= donation.quantity_kg
            allocations[chosen] += donation.quantity_kg
        elapsed.append((perf_counter_ns() - start) / 1_000_000)
        records.append(
            {
                "donation_id": str(donation.id),
                "eligible_count": len(approved),
                "selected_recipient_id": str(chosen) if chosen else None,
                "quantity_kg": donation.quantity_kg,
                "score": ranked.score if ranked else None,
            }
        )
    selected = sum(row["selected_recipient_id"] is not None for row in records)
    elapsed.sort()
    return {
        "strategy": strategy,
        "summary": {
            "submitted": len(records),
            "with_eligible_candidates": sum(row["eligible_count"] > 0 for row in records),
            "selected": selected,
            "no_match": len(records) - selected,
            "selection_policy_violations": 0,  # Selected IDs came from approved candidates.
            "fairness_jain_allocated_kg_all_six_recipients": jain(list(allocations.values())),
            "offline_decision_p50_ms": elapsed[len(elapsed) // 2],
            "offline_decision_p95_ms": elapsed[math.ceil(0.95 * len(elapsed)) - 1],
        },
        "allocations_kg": {str(key): value for key, value in allocations.items()},
        "records": records,
    }


def compare(seed: int, base: datetime, routing=None):
    scenario = generate(seed, base)
    content = json.dumps(scenario, sort_keys=True).encode()
    routes, routing_elapsed_ms = road_routes(scenario, routing) if routing else (None, None)
    map_manifest = ROOT / "data/osrm/manifest.json"
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        sha = None
        dirty = None

    def digest(relative):
        return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()

    return {
        "manifest": {
            "fixture": "synthetic_file_generator; no real donor, recipient or driver data",
            "seed": seed,
            "base_time": base.isoformat(),
            "dataset_sha256": hashlib.sha256(content).hexdigest(),
            "build_sha": sha,
            "working_tree_dirty": dirty,
            "intake_policy_sha256": digest("config/intake.json"),
            "ranking_config_sha256": digest("config/matching.json"),
            "hardware_context": platform.platform(),
            "intake_policy": load_policy().version,
            "ranking_config": load_matching_config().version,
            "model": None,
            "provider": "rules",
            "routing": (
                "osrm_local_road_routes" if routes is not None else "synthetic_fixed_formula"
            ),
            "route_facts_sha256": (
                hashlib.sha256(json.dumps(routes, sort_keys=True).encode()).hexdigest()
                if routes is not None
                else None
            ),
            "routing_precompute_ms": routing_elapsed_ms,
            "local_map_manifest": (
                json.loads(map_manifest.read_text())
                if routes is not None and map_manifest.exists()
                else None
            ),
            "driver_origin": DRIVER_ORIGIN if routes is not None else "synthetic_300_seconds",
            "capacity": "independent per-strategy simulated commitment, no concurrent bookings",
            "completion": "not simulated; pickup/delivery rates cannot be inferred",
        },
        "strategies": [
            replay(scenario, name, routes) for name in ("distance_only", "multi_criteria")
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--base-time", default="2026-10-30T20:00:00+00:00")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evaluation/results/synthetic-2026.json"
    )
    parser.add_argument("--routing-url", help="Local OSRM HTTP URL; otherwise synthetic routes")
    args = parser.parse_args()
    base = datetime.fromisoformat(args.base_time)
    if base.tzinfo is None:
        parser.error("base-time must have a timezone")
    if args.routing_url:
        url = urlsplit(args.routing_url)
        if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1"}:
            parser.error("routing-url must be a local HTTP OSRM endpoint")
    routing = OSRMRouting(args.routing_url, timeout_s=2) if args.routing_url else None
    result = compare(args.seed, base, routing)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Wrote offline comparison: {args.output}")


if __name__ == "__main__":
    main()
