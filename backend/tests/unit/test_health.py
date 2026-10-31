from fastapi.testclient import TestClient

from foodbridge.api.main import create_app
from foodbridge.api.routes import health
from foodbridge.settings import Settings


def test_liveness_needs_no_database():
    client = TestClient(create_app(Settings(_env_file=None)))
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_readiness_returns_503_for_missing_dependency(monkeypatch):
    async def unavailable(_settings):
        return {"database": "unavailable", "redis": "ok"}

    monkeypatch.setattr(health, "check_dependencies", unavailable)
    response = TestClient(create_app()).get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_readiness_requires_both_dependencies(monkeypatch):
    async def available(_settings):
        return {"database": "ok", "redis": "ok"}

    monkeypatch.setattr(health, "check_dependencies", available)
    response = TestClient(create_app()).get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
