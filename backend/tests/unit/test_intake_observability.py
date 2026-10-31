import json

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from pydantic import ValidationError

from foodbridge.api.main import create_app
from foodbridge.integrations.extraction import extract
from foodbridge.observability import logger, registry
from foodbridge.settings import Settings


def test_metrics_are_opt_in_and_local_only():
    default = TestClient(create_app(Settings(_env_file=None)))
    assert default.get("/api/v1/metrics").status_code == 404
    enabled = TestClient(create_app(Settings(_env_file=None, enable_intake_metrics=True)))
    response = enabled.get("/api/v1/metrics")
    assert response.status_code == 200
    assert "duplicate_idempotency_total" in response.text
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", enable_intake_metrics=True)


def test_model_failure_logs_only_metadata_and_review_metrics(caplog):
    from datetime import UTC, datetime
    from uuid import uuid4

    import httpx

    request_id = uuid4()
    settings = Settings(_env_file=None, ai_provider="openai", ai_api_key="private-test-key")
    description = "Contact private-person@example.test. Notes: private donor note."
    logger.addHandler(caplog.handler)
    try:
        result = extract(
            description,
            "UTC",
            datetime(2026, 10, 30, tzinfo=UTC),
            settings,
            httpx.MockTransport(lambda _: httpx.Response(503)),
            request_id,
        )
    finally:
        logger.removeHandler(caplog.handler)
    assert result.provider == "rules"
    records = [
        json.loads(record.message) for record in caplog.records if record.name == logger.name
    ]
    assert records
    assert records[-1]["request_id"] == str(request_id)
    assert records[-1]["duration_ms"] >= 0
    exported = generate_latest(registry).decode()
    assert 'intake_model_calls_total{outcome="http_error"}' in exported
    for sensitive in ("private-test-key", "private-person@example.test", "private donor note"):
        assert sensitive not in caplog.text
        assert sensitive not in exported
