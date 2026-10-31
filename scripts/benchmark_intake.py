"""Local-only synthetic confirmation latency sample; retains its audit/donation records."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from math import ceil
from time import perf_counter
from uuid import uuid4

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()
    if not 5 <= args.samples <= 200:
        parser.error("samples must be between 5 and 200")
    durations = []
    with httpx.Client(base_url=args.url + "/api/v1", timeout=25) as client:
        identity = client.get("/me")
        identity.raise_for_status()
        identity = identity.json()
        if identity["mode"] != "local_demo":
            raise SystemExit("Benchmark requires the opt-in synthetic local demo identity.")
        for _ in range(args.samples):
            description = (
                "Food: synthetic benchmark rice meals. 10 kg. Refrigerated. Allergens: none."
            )
            draft = client.post(
                "/donation-drafts",
                headers={"Idempotency-Key": str(uuid4())},
                json={"description": description, "pickup_location": identity["pickup_location"]},
            )
            draft.raise_for_status()
            draft = draft.json()
            if draft["extraction"]["provider"] != "rules":
                raise SystemExit(
                    "Use FOODBRIDGE_AI_PROVIDER=rules and restart before benchmarking."
                )
            now = datetime.now(UTC)
            command = {
                "draft_id": draft["id"],
                "expected_draft_version": 1,
                "confirmed": True,
                "donation": {
                    "description": description,
                    "food_name": "Synthetic benchmark rice meals",
                    "category": "prepared_meals",
                    "quantity_kg": 10,
                    "packaging_type": "boxed",
                    "storage": "chilled",
                    "dietary_tags": [],
                    "allergens": [],
                    "pickup_location": identity["pickup_location"],
                    "pickup_window": {
                        "start": now.isoformat(),
                        "end": (now + timedelta(hours=2)).isoformat(),
                    },
                    "safe_use_by": (now + timedelta(hours=3)).isoformat(),
                },
            }
            start = perf_counter()
            response = client.post(
                "/donations", headers={"Idempotency-Key": str(uuid4())}, json=command
            )
            response.raise_for_status()
            durations.append((perf_counter() - start) * 1000)
    durations.sort()
    p95 = durations[ceil(0.95 * len(durations)) - 1]
    print(
        json.dumps(
            {
                "samples": len(durations),
                "operation": "POST /donations confirmation",
                "model_included": False,
                "p50_ms": round(durations[len(durations) // 2], 2),
                "p95_ms": round(p95, 2),
                "max_ms": round(durations[-1], 2),
                "p95_target_ms": 2000,
                "passed": p95 <= 2000,
            },
            sort_keys=True,
        )
    )
    if p95 > 2000:
        raise SystemExit("Confirmation p95 exceeds the local 2-second target.")


if __name__ == "__main__":
    main()
