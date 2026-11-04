"""Bounded real HTTP -> DB -> Redis -> workers -> delivery -> SSE smoke, local synthetic only."""

import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

from foodbridge.settings import Settings

BASE = "http://127.0.0.1:8000/api/v1"


def wait_for(callback, predicate, timeout=45):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = callback()
        if predicate(result):
            return result
        time.sleep(0.25)
    raise AssertionError("Timed out waiting for the committed workflow state.")


def run():
    settings = Settings()
    if (
        settings.environment != "local"
        or not settings.enable_local_workflow_demo
        or not settings.enable_local_intake_demo
        or settings.notification_mode != "sandbox"
    ):
        raise SystemExit("Requires local workflow/intake demos and sandbox notifications.")
    with httpx.Client(timeout=10) as client:

        def request(method, path, role="donor", body=None, key=None):
            headers = {"X-FoodBridge-Role": role}
            if method == "POST":
                headers["Idempotency-Key"] = str(key or uuid4())
            response = client.request(method, BASE + path, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

        wait_for(lambda: client.get(BASE + "/health/ready").status_code, lambda code: code == 200)
        identity = request("GET", "/me")
        now = datetime.now(UTC)
        donation = {
            "description": "Synthetic smoke: vegetarian rice, 1 kg, chilled; allergens soy.",
            "food_name": "Rice",
            "category": "prepared_meals",
            "quantity_kg": 1,
            "storage": "chilled",
            "dietary_tags": ["vegetarian"],
            "allergens": ["soy"],
            "pickup_location": identity["pickup_location"],
            "pickup_window": {
                "start": (now - timedelta(minutes=1)).isoformat(),
                "end": (now + timedelta(hours=2)).isoformat(),
            },
            "safe_use_by": (now + timedelta(hours=3)).isoformat(),
        }
        draft = request(
            "POST",
            "/donation-drafts",
            body={
                "description": donation["description"],
                "pickup_location": donation["pickup_location"],
            },
        )
        submitted = request(
            "POST",
            "/donations",
            body={
                "draft_id": draft["id"],
                "expected_draft_version": draft["version"],
                "confirmed": True,
                "donation": donation,
            },
        )
        identifier = submitted["donation"]["id"]
        offered = wait_for(
            lambda: request("GET", f"/donations/{identifier}"),
            lambda value: value["donation"]["status"] == "offered",
        )
        matches = request("GET", "/matches?limit=100", "recipient")["items"]
        match = next(
            item for item in matches if item["recommendation"]["donation_id"] == identifier
        )
        key = uuid4()
        body = {
            "match_id": match["recommendation"]["id"],
            "expected_donation_version": offered["donation"]["version"],
        }
        reserved = request("POST", "/reservations", "recipient", body, key)
        assert request("POST", "/reservations", "recipient", body, key) == reserved

        def pickup_snapshot():
            rows = request("GET", "/pickups?limit=100", "driver")["items"]
            return next((row for row in rows if row["donation_id"] == identifier), None)

        pickup = wait_for(pickup_snapshot, lambda row: row is not None)
        path = f"/pickups/{pickup['id']}"
        accepted = request(
            "POST", path + "/accept", "driver", {"expected_version": pickup["version"]}
        )
        picked = request(
            "POST",
            path + "/confirm-pickup",
            "driver",
            {
                "expected_version": accepted["version"],
                "handling_confirmed": True,
                "observed_quantity_kg": 1,
            },
        )
        delivery_key = uuid4()
        delivery_body = {"expected_version": picked["version"], "delivery_confirmed": True}
        delivered = request(
            "POST", path + "/confirm-delivery", "driver", delivery_body, delivery_key
        )
        assert (
            request("POST", path + "/confirm-delivery", "driver", delivery_body, delivery_key)
            == delivered
        )
        assert delivered["donation"]["status"] == "delivered"
        summary = request("GET", "/operations/summary", "operator")
        assert summary["synthetic"] and summary["delivered_count"] >= 1
        # Keep real streaming coverage bounded; use the replay stream, not in-process helpers.
        seen = False
        with client.stream(
            "GET",
            BASE + "/events",
            headers={"X-FoodBridge-Role": "donor", "Last-Event-ID": "0"},
            timeout=15,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    if event["aggregate_id"] == identifier:
                        seen = True
                        break
        assert seen
        print(
            json.dumps(
                {
                    "synthetic": True,
                    "donation_id": identifier,
                    "status": "delivered",
                    "http_idempotent_replay": "passed",
                    "sse_replay": "passed",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    run()
