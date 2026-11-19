"""Local HTTP/worker/OSRM smoke: posted donation through real routing to delivery."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

import httpx
from scripts.seed_matching_demo import DRIVER_ORIGIN, RECIPIENTS, recipient_id
from scripts.smoke_workflow import wait_for
from sqlalchemy import select

from foodbridge.db.models import Donation, IntakeEvaluation
from foodbridge.db.session import session_factory
from foodbridge.db.workflow_models import MatchOffer
from foodbridge.settings import Settings


def run(
    api_url="http://127.0.0.1:8000/api/v1",
    route_url="http://127.0.0.1:5000",
    *,
    print_result=True,
):
    settings = Settings()
    if (
        settings.environment != "local"
        or not settings.enable_local_matching_demo
        or settings.enable_local_workflow_demo
        or settings.notification_mode != "sandbox"
    ):
        raise SystemExit("Requires local matching demo, live routing and sandbox notifications.")
    with httpx.Client(timeout=45, trust_env=False) as client:

        def request(method, path, role="donor", body=None, org=None, key=None):
            headers = {"X-FoodBridge-Role": role}
            if org is not None:
                headers["X-Organization-ID"] = str(org)
            if method == "POST":
                headers["Idempotency-Key"] = str(key or uuid4())
            response = client.request(method, api_url + path, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

        wait_for(lambda: client.get(api_url + "/health/ready").status_code, lambda v: v == 200)
        location = request("GET", "/me")["pickup_location"]
        driver = request("GET", "/driver-origin", "driver")
        request(
            "POST",
            "/driver-origin",
            "driver",
            {"expected_version": driver["version"], "origin": DRIVER_ORIGIN.model_dump()},
        )
        route_path = (
            route_url
            + f"/route/v1/driving/{location['longitude']},{location['latitude']};"
            + f"{RECIPIENTS[0].longitude},{RECIPIENTS[0].latitude}"
        )

        def route_ready():
            try:
                response = client.get(route_path, params={"overview": "false"})
                return response.status_code == 200 and response.json().get("code") == "Ok"
            except (httpx.HTTPError, ValueError):
                return False

        wait_for(route_ready, bool, timeout=60)
        now = datetime.now(UTC)
        donation = {
            "description": "Local routing smoke: 1 kg vegetarian chilled rice; allergens soy.",
            "food_name": "Rice",
            "category": "prepared_meals",
            "quantity_kg": 1,
            "storage": "chilled",
            "dietary_tags": ["vegetarian"],
            "allergens": ["soy"],
            "pickup_location": location,
            "pickup_window": {
                "start": (now - timedelta(minutes=1)).isoformat(),
                "end": (now + timedelta(hours=2)).isoformat(),
            },
            "safe_use_by": (now + timedelta(hours=3)).isoformat(),
        }
        draft = request(
            "POST",
            "/donation-drafts",
            body={"description": donation["description"], "pickup_location": location},
        )
        submitted_at = monotonic()
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
        donation_id = submitted["donation"]["id"]
        offered = wait_for(
            lambda: request("GET", f"/donations/{donation_id}"),
            lambda value: value["donation"]["status"] == "offered",
            timeout=75,
        )
        client_offer_latency_ms = (monotonic() - submitted_at) * 1000
        match = None
        chosen_org = None
        for index in range(len(RECIPIENTS)):
            org = recipient_id(index)
            matches = request("GET", "/matches?limit=100&order=newest", "recipient", org=org)[
                "items"
            ]
            match = next(
                (item for item in matches if item["recommendation"]["donation_id"] == donation_id),
                None,
            )
            if match:
                chosen_org = org
                break
        assert match and chosen_org, "No fixture recipient received the offer."
        with session_factory(settings.database_url)() as session:
            offer = session.scalar(
                select(MatchOffer).where(MatchOffer.id == match["recommendation"]["id"])
            )
            evaluation = session.get(IntakeEvaluation, offer.evaluation_id)
            donation_row = session.get(Donation, offer.donation_id)
            assert not evaluation.batch["synthetic"]
            assert offer.candidate["route"]["source"] == "routing_provider"
            server_offer_latency_ms = (
                offer.created_at - donation_row.created_at
            ).total_seconds() * 1000
        body = {
            "match_id": match["recommendation"]["id"],
            "expected_donation_version": offered["donation"]["version"],
        }
        key = uuid4()
        reserved = request("POST", "/reservations", "recipient", body, chosen_org, key)
        assert request("POST", "/reservations", "recipient", body, chosen_org, key) == reserved

        def pickup_snapshot():
            rows = request("GET", "/pickups?limit=100&order=newest", "driver")["items"]
            return next((row for row in rows if row["donation_id"] == donation_id), None)

        pickup = wait_for(pickup_snapshot, lambda row: row is not None, timeout=75)
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
        delivered = request(
            "POST",
            path + "/confirm-delivery",
            "driver",
            {"expected_version": picked["version"], "delivery_confirmed": True},
        )
        assert delivered["donation"]["status"] == "delivered"
        summary = request("GET", "/operations/summary", "operator")
        assert summary["delivered_count"] >= 1
        seen = False
        with client.stream(
            "GET",
            api_url + "/events",
            headers={"X-FoodBridge-Role": "donor", "Last-Event-ID": "0"},
            timeout=15,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if (
                    line.startswith("data: ")
                    and json.loads(line[6:])["aggregate_id"] == donation_id
                ):
                    seen = True
                    break
        assert seen, "The donor did not receive a persisted SSE event."
        result = {
            "donation_id": donation_id,
            "status": "delivered",
            "routing": "OSRM HTTP; persisted non-synthetic route",
            "recipient_organization_id": str(chosen_org),
            "quantity_kg": donation["quantity_kg"],
            "road_distance_m": match["recommendation"]["distance_m"],
            "server_recorded_submission_to_offer_ms": server_offer_latency_ms,
            "client_observed_submission_to_offer_ms": client_offer_latency_ms,
            "sse_replay": "passed",
        }
        if print_result:
            print(json.dumps(result, indent=2))
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--routing-url", default="http://127.0.0.1:5000")
    args = parser.parse_args()
    run(args.api_url, args.routing_url)
