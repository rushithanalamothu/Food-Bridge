"""Bounded HTTP -> PostgreSQL -> real broker/worker smoke for an explicitly seeded local demo."""

import argparse
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    with httpx.Client(base_url=args.url + "/api/v1", timeout=15) as client:
        for _ in range(30):
            try:
                client.get("/health/live").raise_for_status()
                break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise SystemExit("API did not become available within the smoke startup window.")
        identity = client.get("/me")
        identity.raise_for_status()
        identity = identity.json()
        if identity["mode"] != "local_demo":
            raise SystemExit("This smoke writes synthetic demo data and requires local_demo mode.")
        now = datetime.now(UTC)
        description = (
            "Food: vegetable rice bowls. 20 meals, 10 kg. Refrigerated. Vegetarian. Allergens: soy."
        )
        draft = client.post(
            "/donation-drafts",
            headers={"Idempotency-Key": str(uuid4())},
            json={"description": description, "pickup_location": identity["pickup_location"]},
        )
        draft.raise_for_status()
        draft = draft.json()
        assert draft["extraction"]["fields"]["quantity_kg"] == 10
        assert draft["extraction"]["fields"]["safe_use_by"] is None
        body = {
            "draft_id": draft["id"],
            "expected_draft_version": 1,
            "confirmed": True,
            "donation": {
                "description": description,
                "food_name": "Vegetable rice bowls",
                "category": "prepared_meals",
                "quantity_kg": 10,
                "portions": 20,
                "storage": "chilled",
                "dietary_tags": ["vegetarian"],
                "allergens": ["soy"],
                "pickup_location": identity["pickup_location"],
                "pickup_window": {
                    "start": (now + timedelta(hours=1)).isoformat(),
                    "end": (now + timedelta(hours=3)).isoformat(),
                },
                "safe_use_by": (now + timedelta(hours=4)).isoformat(),
                "handling_notes": "Synthetic smoke",
            },
        }
        key = {"Idempotency-Key": str(uuid4())}
        donation = client.post("/donations", headers=key, json=body)
        donation.raise_for_status()
        donation = donation.json()
        assert client.post("/donations", headers=key, json=body).json() == donation
        identifier = donation["donation"]["id"]
        assert client.get(f"/donations/{identifier}").json()["donation"]["id"] == identifier
        job = client.post(
            f"/donations/{identifier}/demo-eligibility", headers={"Idempotency-Key": str(uuid4())}
        )
        job.raise_for_status()
        job_id = job.json()["id"]
        print(f"Draft confirmed; donation {identifier}; waiting for worker {job_id}.", flush=True)
        for _ in range(30):
            response = client.get(f"/intake/evaluations/{job_id}")
            response.raise_for_status()
            result = response.json()
            if result["status"] != "pending":
                break
            time.sleep(1)
        else:
            raise SystemExit("Eligibility still pending after 30s. Check intake worker and relay.")
        assert result["status"] == "completed", result
        assert result["result"]["synthetic"] is True
        decisions = result["result"]["decisions"]
        assert decisions[0]["eligible"]
        assert "insufficient_capacity" in decisions[1]["reasons"]
        print(
            "PASS: persisted draft -> confirmed donation -> idempotent replay "
            "-> broker -> eligibility worker."
        )


if __name__ == "__main__":
    main()
