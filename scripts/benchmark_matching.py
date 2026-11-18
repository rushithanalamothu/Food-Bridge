"""Serial local full-stack comparison run; each strategy requires its own empty database."""

import argparse
import hashlib
import json
import math
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from scripts.seed_matching_demo import RECIPIENTS, recipient_id
from scripts.smoke_matching import run
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from foodbridge.db.models import Donation
from foodbridge.db.session import session_factory
from foodbridge.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, rank):
    ordered = sorted(values)
    return ordered[math.ceil(rank * len(ordered)) - 1] if ordered else None


def summarize(rows):
    allocations = {str(recipient_id(index)): 0 for index in range(len(RECIPIENTS))}
    for row in rows:
        recipient = row["recipient_organization_id"]
        allocations[recipient] = allocations.get(recipient, 0) + row["quantity_kg"]
    values = list(allocations.values())
    total = sum(values)
    return {
        "attempted": len(rows),
        "delivered_under_local_script": sum(row["status"] == "delivered" for row in rows),
        "server_recorded_offer_p50_ms": percentile(
            [row["server_recorded_submission_to_offer_ms"] for row in rows], 0.5
        ),
        "server_recorded_offer_p95_ms": percentile(
            [row["server_recorded_submission_to_offer_ms"] for row in rows], 0.95
        ),
        "client_observed_offer_p95_ms": percentile(
            [row["client_observed_submission_to_offer_ms"] for row in rows], 0.95
        ),
        "allocation_kg_by_fixture_recipient": allocations,
        "fairness_jain_across_fixture_recipients": (
            total**2 / (len(values) * sum(v * v for v in values)) if total else None
        ),
    }


def benchmark(strategy, count, output, api_url, route_url):
    if output.exists():
        raise SystemExit(f"Output already exists: {output}")
    settings = Settings()
    if (
        settings.environment != "local"
        or not settings.enable_local_matching_demo
        or settings.matching_algorithm != strategy
        or make_url(settings.database_url).host not in {"localhost", "127.0.0.1"}
    ):
        raise SystemExit("Benchmark requires a local matching demo and the selected strategy.")
    with session_factory(settings.database_url)() as session:
        existing = session.scalar(select(func.count()).select_from(Donation))
    if existing:
        raise SystemExit("This database already contains donations. Use a new Compose project.")
    project = os.environ.get("COMPOSE_PROJECT_NAME")
    if not project:
        raise SystemExit("Set a unique COMPOSE_PROJECT_NAME for this strategy's fresh database.")
    map_manifest = ROOT / "data/osrm/manifest.json"
    if not map_manifest.exists():
        raise SystemExit("Prepare a local OSRM dataset before benchmarking.")
    routing = json.loads(map_manifest.read_text())
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    )
    if dirty:
        raise SystemExit("Commit the benchmark code first so both runs use an identical build.")
    manifest = {
        "strategy": strategy,
        "fixture": "two synthetic recipients, one synthetic driver, serial 1kg donations",
        "run_started_at": datetime.now(UTC).isoformat(),
        "count": count,
        "compose_project": project,
        "build_sha": sha,
        "working_tree_dirty": dirty,
        "ranking_config_sha256": hashlib.sha256(
            (ROOT / "config/matching.json").read_bytes()
        ).hexdigest(),
        "intake_policy_sha256": hashlib.sha256(
            (ROOT / "config/intake.json").read_bytes()
        ).hexdigest(),
        "routing_map": routing,
        "scope": "local HTTP, PostGIS, OSRM, Redis and workers; scripted pickup/delivery only",
        "limitations": (
            "Each strategy needs a separate fresh Compose database. Serial arrivals and scripted "
            "acceptance are not representative of real users or concurrent traffic."
        ),
    }
    rows = []
    error = None
    started = monotonic()
    try:
        for index in range(count):
            print(f"Listing {index + 1}/{count} ({strategy})", flush=True)
            rows.append(run(api_url, route_url, print_result=False))
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)[:300]}
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        result = {
            "manifest": manifest,
            "summary": summarize(rows),
            "elapsed_s": monotonic() - started,
            "error": error,
            "records": rows,
        }
        with output.open("x") as file:
            json.dump(result, file, indent=2, sort_keys=True)
            file.write("\n")
        print(f"Wrote {len(rows)}/{count} raw records to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=["distance_only", "multi_criteria"], required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--routing-url", default="http://127.0.0.1:5000")
    args = parser.parse_args()
    if not 1 <= args.count <= 40:
        parser.error("count must be between 1 and 40")
    benchmark(args.strategy, args.count, args.output, args.api_url, args.routing_url)
