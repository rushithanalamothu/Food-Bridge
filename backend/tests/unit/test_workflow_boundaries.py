"""Workflow boundary tests require neither database nor provider credentials."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from foodbridge.agents.orchestrator.service import provider_call
from foodbridge.api.main import create_app
from foodbridge.auth.workflow import current_actor
from foodbridge.db.workflow import amount, require_role
from foodbridge.domain.errors import AppError
from foodbridge.domain.workflow import (
    Actor,
    DeliveryConfirmation,
    PickupConfirmation,
    VersionCommand,
)
from foodbridge.integrations.workflow import (
    DependencyUnavailable,
    UnconfiguredMatching,
    matching_gateway,
)
from foodbridge.settings import Settings


@pytest.mark.parametrize(
    "path",
    ["/session", "/matches", "/pickups", "/operations/summary", "/operations/failures", "/events"],
)
def test_workflow_reads_require_verified_identity(path):
    client = TestClient(create_app(Settings(ai_provider="rules")))
    response = client.get("/api/v1" + path)
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
    assert response.json()["request_id"]


@pytest.mark.parametrize(
    "body,model",
    [
        ({"expected_version": 0}, VersionCommand),
        ({"expected_version": 1, "status": "delivered"}, VersionCommand),
        (
            {"expected_version": 1, "handling_confirmed": False, "observed_quantity_kg": 1},
            PickupConfirmation,
        ),
        (
            {
                "expected_version": 1,
                "handling_confirmed": True,
                "observed_quantity_kg": float("nan"),
            },
            PickupConfirmation,
        ),
        ({"expected_version": 1, "delivery_confirmed": False}, DeliveryConfirmation),
    ],
)
def test_commands_reject_unconfirmed_invalid_or_client_selected_states(body, model):
    with pytest.raises(ValidationError):
        model.model_validate(body)


@pytest.mark.parametrize("quantity", [0, -1, 0.0001, 1.00001])
def test_quantity_adjustments_require_valid_precision(quantity):
    with pytest.raises(AppError) as error:
        amount(quantity)
    assert error.value.status == 422


def test_recipient_cannot_act_as_driver():
    actor = Actor(user_id=uuid4(), organization_id=uuid4(), role="recipient")
    with pytest.raises(AppError) as error:
        require_role(actor, "driver")
    assert error.value.status == 403


@pytest.mark.parametrize(
    "mode", [{"enable_local_workflow_demo": True}, {"notification_mode": "sandbox"}]
)
def test_synthetic_runtime_is_rejected_outside_local(mode):
    with pytest.raises(ValidationError):
        Settings(environment="production", ai_provider="rules", **mode)


def test_unconfigured_matching_cannot_report_success():
    gateway = matching_gateway(Settings(ai_provider="rules"))
    assert isinstance(gateway, UnconfiguredMatching)
    with pytest.raises(DependencyUnavailable):
        gateway.candidates(None, set(), set())


def test_malformed_bearer_never_falls_back_to_local_workflow_demo():
    app = create_app(Settings(ai_provider="rules", enable_local_workflow_demo=True))
    request = Request(
        {"type": "http", "headers": [(b"authorization", b"Basic invalid")], "app": app}
    )
    with pytest.raises(AppError) as error:
        current_actor(request, None)
    assert error.value.code == "invalid_token"


def test_bearer_selection_cannot_override_verification(monkeypatch):
    app = create_app(Settings(ai_provider="rules", enable_local_workflow_demo=True))

    def reject(*_):
        raise AppError("invalid_token", "Rejected.", 401)

    monkeypatch.setattr("foodbridge.auth.workflow.verified_subject", reject)
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", b"Bearer invalid"), (b"x-foodbridge-role", b"operator")],
            "app": app,
        }
    )
    with pytest.raises(AppError) as error:
        current_actor(request, None)
    assert error.value.status == 401


def test_arbitrary_provider_errors_are_sanitized():
    def provider():
        raise RuntimeError("secret-provider-payload")

    with pytest.raises(DependencyUnavailable) as error:
        provider_call(provider)
    assert str(error.value) == "provider_failure"


def test_unknown_dependency_reason_is_not_exposed():
    assert str(DependencyUnavailable("secret-provider-payload")) == "provider_failure"
