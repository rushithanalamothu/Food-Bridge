import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from foodbridge.api.main import create_app
from foodbridge.settings import Settings


def test_deployment_metrics_are_not_public():
    client = TestClient(
        create_app(
            Settings(_env_file=None, ai_provider="rules", metrics_token="private-monitoring")
        )
    )
    assert client.get("/internal/metrics").status_code == 404
    assert (
        client.get("/internal/metrics", headers={"Authorization": "Bearer incorrect"}).status_code
        == 404
    )


def test_shared_deployment_requires_https_for_cookie_and_smtp():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ai_provider="rules",
            environment="production",
            public_url="http://site.example",
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ai_provider="rules",
            environment="production",
            public_url="https://site.example",
            notification_mode="smtp",
            smtp_host="smtp.example",
            smtp_security="none",
        )


def test_deployment_generator_keeps_secrets_private_and_refuses_overwrite(tmp_path):
    import json

    spec = importlib.util.spec_from_file_location(
        "init_deployment", Path("scripts/init_deployment.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.initialize(
        tmp_path,
        "food.example.test",
        "login.example.test",
        "registry.example.test/api:review-sha",
        "registry.example.test/web:review-sha",
    )
    private = tmp_path / "runtime.env"
    assert private.stat().st_mode & 0o777 == 0o600
    assert "FOODBRIDGE_ENABLE_LOCAL_WORKFLOW_DEMO='false'" in private.read_text()
    realm = json.loads((tmp_path / "realm.json").read_text())
    assert realm["users"] == [] and realm["sslRequired"] == "external"
    assert realm["loginTheme"] == "foodbridge"
    assert realm["smtpServer"] == {}
    assert realm["registrationAllowed"] is False
    assert realm["resetPasswordAllowed"] is False
    assert realm["verifyEmail"] is True
    assert realm["clients"][0]["redirectUris"] == ["https://food.example.test/api/v1/auth/callback"]
    with pytest.raises(ValueError, match="refusing"):
        module.initialize(tmp_path, "food.example.test", "login.example.test", "api:sha", "web:sha")


def test_release_rollback_preserves_history_and_never_downgrades_schema(tmp_path, monkeypatch):
    import json
    import sys

    spec = importlib.util.spec_from_file_location(
        "release_control", Path("scripts/release_control.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = tmp_path / "runtime.env"
    env.write_text(
        "FOODBRIDGE_BACKEND_IMAGE='example/api:old-sha'\nFOODBRIDGE_WEB_IMAGE='example/web:old-sha'\nFOODBRIDGE_PUBLIC_URL='https://food.example.test'\n"
    )
    commands = []
    monkeypatch.setattr(
        module.subprocess, "run", lambda command, **kwargs: commands.append(command)
    )
    promoted = tmp_path / "promoted.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_control",
            "--env-file",
            str(env),
            "--record",
            str(promoted),
            "--backend-image",
            "example/api:new-sha",
            "--web-image",
            "example/web:new-sha",
        ],
    )
    module.main()
    assert json.loads(promoted.read_text())["verified"] is False
    assert json.loads(promoted.read_text())["gateway_verified"] is True
    assert any("migrate" in c and "run" in c for c in commands)
    commands.clear()
    rolled = tmp_path / "rolled.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_control",
            "--env-file",
            str(env),
            "--record",
            str(rolled),
            "--rollback",
            str(promoted),
        ],
    )
    module.main()
    assert "example/api:old-sha" in env.read_text()
    assert (
        json.loads(rolled.read_text())["selected"]["FOODBRIDGE_WEB_IMAGE"] == "example/web:old-sha"
    )
    assert any("--no-deps" in c for c in commands)
    assert not any("downgrade" in c or ("migrate" in c and "run" in c) for c in commands)
