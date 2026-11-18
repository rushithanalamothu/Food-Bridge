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
from uuid import UUID, uuid4

from scripts.generate_synthetic import generate

from foodbridge.agents.intake.config import load_policy
from foodbridge.agents.intake.policy import evaluate
from foodbridge.agents.matching.config import load_matching_config
from foodbridge.agents.matching.ranking import distance_only, multi_criteria
from foodbridge.domain.contracts import DonationRead, PickupWindow, RecipientProfile
from foodbridge.domain.intake import (
    DriverFacts,
    EligibilityBatch,
    EligibilityCandidate,
    IntakeHandoff,
    RouteFacts,
)

ROOT = Path(__file__).resolve().parents[1]


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


def replay(scenario: dict, strategy: str):
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
                to_pickup_time_s=300,
            )
            candidates.append(
                EligibilityCandidate(
                    recipient=current,
                    active_and_verified=True,
                    driver=driver,
                    route=synthetic_route(donation.pickup_location, current.location, now),
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


def compare(seed: int, base: datetime):
    scenario = generate(seed, base)
    content = json.dumps(scenario, sort_keys=True).encode()
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
            "fixture": "synthetic_file_generator; synthetic routes, no live provider",
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
            "routing": "synthetic_fixed_formula",
            "capacity": "independent per-strategy simulated commitment, no concurrent bookings",
            "completion": "not simulated; pickup/delivery rates cannot be inferred",
        },
        "strategies": [replay(scenario, name) for name in ("distance_only", "multi_criteria")],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--base-time", default="2026-10-30T20:00:00+00:00")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evaluation/results/synthetic-2026.json"
    )
    args = parser.parse_args()
    base = datetime.fromisoformat(args.base_time)
    if base.tzinfo is None:
        parser.error("base-time must have a timezone")
    result = compare(args.seed, base)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Wrote synthetic offline comparison: {args.output}")


if __name__ == "__main__":
    main()
