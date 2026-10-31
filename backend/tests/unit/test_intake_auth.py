from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from foodbridge.api.main import create_app
from foodbridge.auth import identity
from foodbridge.domain.errors import AppError
from foodbridge.settings import Settings


@pytest.fixture
def oidc(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        identity,
        "jwks_client",
        lambda _: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())
        ),
    )
    settings = Settings(
        _env_file=None,
        oidc_issuer="https://issuer.example/",
        oidc_audience="foodbridge",
        oidc_jwks_url="https://issuer.example/jwks",
    )
    now = datetime.now(UTC)
    claims = {
        "sub": "known-donor",
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return key, settings, claims


def test_valid_jwt_subject_is_verified(oidc):
    key, settings, claims = oidc
    assert (
        identity.verified_subject(jwt.encode(claims, key, algorithm="RS256"), settings)
        == "known-donor"
    )


@pytest.mark.parametrize(
    ("claim", "value"),
    [("iss", "https://other.example/"), ("aud", "other-app"), ("exp", 1), ("sub", "")],
)
def test_invalid_claims_are_rejected(oidc, claim, value):
    key, settings, claims = oidc
    claims[claim] = value
    with pytest.raises(AppError) as error:
        identity.verified_subject(jwt.encode(claims, key, algorithm="RS256"), settings)
    assert error.value.status == 401


def test_demo_is_disabled_by_default_and_no_data_is_exposed():
    client = TestClient(create_app(Settings(_env_file=None)))
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/donations").status_code == 401


def test_demo_cannot_be_enabled_in_shared_environment():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", enable_local_intake_demo=True)
