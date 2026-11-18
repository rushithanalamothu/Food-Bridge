"""Routing failure boundaries and ranking over the intake-approved cohort."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from foodbridge.agents.intake.demo import demo_batch
from foodbridge.agents.intake.policy import evaluate, urgency
from foodbridge.agents.matching.config import MatchingConfig, load_matching_config
from foodbridge.agents.matching.ranking import distance_only, multi_criteria
from foodbridge.agents.matching.routing import NoRoute, OSRMRouting
from foodbridge.agents.matching.service import LiveMatching, ModelChoice
from foodbridge.domain.contracts import DonationInput, DonationRead
from foodbridge.domain.errors import AppError
from foodbridge.domain.intake import IntakeDonationRead, IntakeHandoff
from foodbridge.integrations.workflow import DependencyUnavailable, matching_gateway
from foodbridge.settings import Settings

NOW = datetime(2026, 10, 30, 22, tzinfo=UTC)
EXAMPLE = Path(__file__).resolve().parents[3] / "contracts/examples/donation-input.json"


def handoff():
    value = DonationInput.model_validate_json(EXAMPLE.read_text())
    donation = DonationRead(
        **value.model_dump(),
        id=uuid4(),
        donor_organization_id=uuid4(),
        status="matching",
        version=2,
        created_at=NOW,
    )
    batch = demo_batch(IntakeDonationRead(donation=donation, urgency=urgency(value, NOW)), NOW)
    result = evaluate(donation, batch, NOW)
    approved = {d.recipient_organization_id for d in result.decisions if d.eligible}
    return IntakeHandoff(
        evaluation_id=uuid4(),
        donation=donation,
        result=result,
        eligible_candidates=[
            c for c in batch.candidates if c.recipient.organization_id in approved
        ],
    )


def test_unconfigured_and_configured_gateway():
    settings = Settings(ai_provider="rules", routing_base_url="http://localhost:5000")
    assert isinstance(matching_gateway(settings), LiveMatching)
    with pytest.raises(ValidationError):
        Settings(ai_provider="rules", routing_base_url="http://remote.example:5000")


def test_nonfinite_ranking_weights_fail_configuration():
    values = load_matching_config().model_dump()
    values["weights"]["distance"] = float("nan")
    with pytest.raises(ValidationError):
        MatchingConfig.model_validate(values)


@pytest.mark.parametrize(
    "payload,exception",
    [
        ({"code": "NoRoute", "routes": []}, NoRoute),
        ({"code": "Ok", "routes": [{"distance": -1, "duration": 20}]}, DependencyUnavailable),
        (
            {"code": "Ok", "routes": [{"distance": 10, "duration": float("inf")}]},
            DependencyUnavailable,
        ),
        (["bad"], DependencyUnavailable),
        ({"code": "Error"}, DependencyUnavailable),
    ],
)
def test_routing_rejects_unusable_routes(payload, exception):
    adapter = OSRMRouting(
        "http://localhost:5000",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    origin = handoff().donation.pickup_location
    with pytest.raises(exception):
        adapter.estimate(origin, origin)


def test_routing_uses_lon_lat_metres_seconds_and_bounded_timeout():
    def respond(request):
        assert "/route/v1/driving/-121." in str(request.url)
        assert "overview=false" in str(request.url)
        return httpx.Response(
            200, json={"code": "Ok", "routes": [{"distance": 1250, "duration": 345}]}
        )

    origin = handoff().donation.pickup_location
    route = OSRMRouting(
        "http://localhost:5000", timeout_s=2, transport=httpx.MockTransport(respond)
    )
    assert route.estimate(origin, origin).distance_m == 1250
    assert route.estimate(origin, origin).travel_time_s == 345


def test_local_osrm_is_reachable_even_with_an_ambient_socks_proxy(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps(
                {"code": "Ok", "routes": [{"distance": 1500, "duration": 240}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1")
    try:
        origin = handoff().donation.pickup_location
        route = OSRMRouting(f"http://127.0.0.1:{server.server_port}", timeout_s=2)
        assert route.estimate(origin, origin).distance_m == 1500
    finally:
        server.shutdown()
        server.server_close()


def test_routing_timeout_is_retryable_and_sanitized():
    def timeout(request):
        raise httpx.ReadTimeout("secret-route-url", request=request)

    origin = handoff().donation.pickup_location
    with pytest.raises(DependencyUnavailable, match="routing_service_unavailable"):
        OSRMRouting("https://routes.example", transport=httpx.MockTransport(timeout)).estimate(
            origin, origin
        )


def test_distance_only_and_multicriteria_reject_ineligible_model_candidate(monkeypatch):
    item = handoff()
    chosen = distance_only(item)
    assert chosen.candidate.recipient.organization_id in {
        d.recipient_organization_id for d in item.result.decisions if d.eligible
    }
    assert multi_criteria(item, load_matching_config(), {})
    item.eligible_candidates[0].recipient.version += 1
    assert distance_only(item) is None

    item = handoff()
    service = LiveMatching(Settings(ai_provider="rules"), None, clock=lambda: NOW)
    monkeypatch.setattr(service, "_allocations", lambda *_: {})
    service.settings.matching_algorithm = "multi_criteria"
    service.settings.ai_provider = "openai"
    service.settings.ai_model = "test-model"
    monkeypatch.setattr(
        "foodbridge.agents.matching.service.generate_structured",
        lambda *_args, **_kwargs: ModelChoice(selected_recipient_id=uuid4()),
    )
    result = service.rank(item, 1)
    assert result.recipient_organization_id in {
        d.recipient_organization_id for d in item.result.decisions if d.eligible
    }
    assert result.ranking_evidence.fallback_reason == "invalid_or_unavailable_model_choice"
    assert result.ranking_evidence.provider == "openai"
    assert result.ranking_evidence.prompt_version == "matching-choice-v1"


def test_fairness_can_change_order_only_after_policy_approval():
    item = handoff()
    original = item.eligible_candidates[0]
    alternative = original.model_copy(deep=True)
    alternative.recipient.organization_id = uuid4()
    alternative.route.distance_m = 100
    alternative.recipient.available_capacity_kg_by_storage[item.donation.storage] = 20
    item.eligible_candidates.append(alternative)
    item.result.decisions.append(
        item.result.decisions[0].model_copy(
            update={"recipient_organization_id": alternative.recipient.organization_id}
        )
    )
    assert (
        distance_only(item).candidate.recipient.organization_id
        == alternative.recipient.organization_id
    )
    allocations = {alternative.recipient.organization_id: 1000.0}
    assert multi_criteria(item, load_matching_config(), allocations)[0].candidate == original
    item.result.decisions[-1].eligible = False
    assert distance_only(item).candidate == original


def test_database_allocation_units_are_normalized_before_weighting(monkeypatch):
    item = handoff()
    identifier = item.eligible_candidates[0].recipient.organization_id

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, query):
            sql = str(query)
            assert "reservations" in sql and "quantity_kg" in sql
            return SimpleNamespace(all=lambda: [(identifier, Decimal("10.000"))])

    service = LiveMatching(Settings(ai_provider="rules"), None, clock=lambda: NOW)
    monkeypatch.setattr(service, "sessions", lambda: Session())
    recommendation = service.rank(item, 1)
    assert recommendation.ranking_evidence.features["fairness"] == 0.0


def test_empty_and_stale_handoff_never_produce_offer():
    item = handoff()
    service = LiveMatching(
        Settings(ai_provider="rules", matching_algorithm="distance_only"), None, clock=lambda: NOW
    )
    item.eligible_candidates = []
    assert service.rank(item, 1) is None
    item = handoff()
    service.clock = lambda: NOW + timedelta(seconds=301)
    with pytest.raises(AppError, match="Route facts expired"):
        service.rank(item, 1)
    item.result.donation_version += 1
    with pytest.raises(AppError, match="Eligibility policy changed"):
        service.rank(item, 1)
