"""OIDC boundaries without a live provider: state, nonce, cookie, refresh and CSRF."""

import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from foodbridge.api.main import create_app
from foodbridge.auth import browser, identity
from foodbridge.settings import Settings


class MemoryRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, ex=None, xx=False):
        if xx and key not in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def getdel(self, key):
        return self.values.pop(key, None)

    def delete(self, key):
        self.values.pop(key, None)

    def lock(self, *args, **kwargs):
        return SimpleNamespace(acquire=lambda: True, release=lambda: None)


@pytest.fixture
def browser_env(monkeypatch):
    settings = Settings(
        _env_file=None,
        ai_provider="rules",
        browser_auth_enabled=True,
        oidc_issuer="https://identity.example/realms/foodbridge",
        oidc_audience="foodbridge-api",
        oidc_jwks_url="https://identity.example/jwks",
        oidc_client_id="foodbridge-web",
    )
    redis = MemoryRedis()
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(browser, "store", lambda _: redis)
    monkeypatch.setattr(
        browser,
        "discovery",
        lambda *args: {
            "authorization_endpoint": "https://identity.example/auth",
            "token_endpoint": "https://identity.example/token",
        },
    )
    monkeypatch.setattr(
        identity,
        "jwks_client",
        lambda _: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=signing.public_key())
        ),
    )
    app = create_app(settings)

    def token(aud, **extra):
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": "verified-user",
                "aud": aud,
                "iss": settings.oidc_issuer,
                "iat": now,
                "exp": now + timedelta(minutes=5),
                **extra,
            },
            signing,
            algorithm="RS256",
        )

    return SimpleNamespace(settings=settings, redis=redis, client=TestClient(app), token=token)


def login_state(env):
    response = env.client.get(
        "/api/v1/auth/login?return_to=https://evil.example", follow_redirects=False
    )
    assert response.status_code == 302
    params = parse_qs(urlsplit(response.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert "HttpOnly" in response.headers["set-cookie"]
    state = params["state"][0]
    saved = json.loads(env.redis.get(browser.key("login", state)))
    assert saved["return_to"] == "/"
    return state, saved


def test_callback_binds_nonce_state_pkce_and_rotates_session(browser_env, monkeypatch):
    env = browser_env
    state, saved = login_state(env)

    def post(url, **kwargs):
        assert kwargs["data"]["code_verifier"] == saved["verifier"]
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "access_token": env.token("foodbridge-api"),
                "id_token": env.token("foodbridge-web", nonce=saved["nonce"]),
                "token_type": "Bearer",
                "expires_in": 300,
                "refresh_token": "private-refresh",
            },
        )

    monkeypatch.setattr(browser.httpx, "post", post)
    response = env.client.get(
        f"/api/v1/auth/callback?state={state}&code=one-use-code", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["cache-control"] == "no-store"
    cookie = env.client.cookies.get(browser.COOKIE)
    assert (
        cookie
        and "private-refresh" not in response.text
        and env.token("foodbridge-api") not in response.text
    )
    assert json.loads(env.redis.get(browser.key("session", cookie)))["subject"] == "verified-user"
    assert env.client.get(f"/api/v1/auth/callback?state={state}&code=replay").status_code == 400


def test_wrong_state_and_nonce_cannot_create_session(browser_env, monkeypatch):
    env = browser_env
    state, _ = login_state(env)
    assert env.client.get("/api/v1/auth/callback?state=wrong&code=code").status_code == 400
    monkeypatch.setattr(
        browser.httpx,
        "post",
        lambda *a, **kw: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "access_token": env.token("foodbridge-api"),
                "id_token": env.token("foodbridge-web", nonce="wrong"),
                "token_type": "Bearer",
                "expires_in": 300,
            },
        ),
    )
    assert env.client.get(f"/api/v1/auth/callback?state={state}&code=code").status_code == 400
    assert env.client.cookies.get(browser.COOKIE) is None


def test_cookie_session_rejects_csrf_and_invalid_session_never_falls_back(browser_env):
    env = browser_env
    env.client.cookies.set(browser.COOKIE, "missing", domain="testserver.local", path="/")
    assert (
        env.client.post(
            "/api/v1/auth/logout", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert env.client.get("/api/v1/session").status_code == 401
    assert (
        env.client.post(
            "/api/v1/auth/logout", headers={"Origin": env.settings.public_url}
        ).status_code
        == 200
    )
    assert env.client.cookies.get(browser.COOKIE) is None


def test_refresh_stays_server_side_and_logout_invalidates(browser_env, monkeypatch):
    env = browser_env
    sid = "opaque-session"
    saved = {
        "subject": "verified-user",
        "access_token": env.token("foodbridge-api"),
        "refresh_token": "old-refresh",
        "expires_at": 0,
        "absolute_expiry": time.time() + 300,
    }
    env.redis.set(browser.key("session", sid), json.dumps(saved))
    env.client.cookies.set(browser.COOKIE, sid)
    monkeypatch.setattr(
        browser.httpx,
        "post",
        lambda *a, **kw: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "access_token": env.token("foodbridge-api"),
                "refresh_token": "rotated-refresh",
                "token_type": "Bearer",
                "expires_in": 300,
            },
        ),
    )
    request = SimpleNamespace(
        cookies={browser.COOKIE: sid},
        method="GET",
        app=SimpleNamespace(state=SimpleNamespace(settings=env.settings)),
    )
    assert browser.browser_subject(request) == "verified-user"
    assert (
        json.loads(env.redis.get(browser.key("session", sid)))["refresh_token"] == "rotated-refresh"
    )
    result = env.client.post("/api/v1/auth/logout", headers={"Origin": env.settings.public_url})
    assert result.status_code == 200 and env.redis.get(browser.key("session", sid)) is None


@pytest.mark.parametrize(
    "address", ["a@example.test\r\nBcc: victim@example.test", "bad", "a@b", "a b@example.test"]
)
def test_contact_validation_rejects_header_injection(address):
    from foodbridge.integrations.email import valid_email

    with pytest.raises(ValueError):
        valid_email(address)


def test_browser_auth_does_not_fall_back_to_demo_after_logout(browser_env):
    settings = browser_env.settings.model_copy(
        update={"enable_local_workflow_demo": True, "enable_local_intake_demo": True}
    )
    client = TestClient(create_app(settings))
    assert client.get("/api/v1/auth/session").json()["authenticated"] is False
    assert client.get("/api/v1/session").status_code == 401
    assert client.get("/api/v1/me").status_code == 401


def test_absolute_session_expiry_cannot_be_extended_by_refresh(browser_env, monkeypatch):
    env = browser_env
    sid = "absolute-expired"
    env.redis.set(
        browser.key("session", sid),
        json.dumps(
            {
                "subject": "verified-user",
                "expires_at": 0,
                "absolute_expiry": time.time() - 1,
                "refresh_token": "private",
            }
        ),
    )
    monkeypatch.setattr(
        browser.httpx, "post", lambda *a, **kw: pytest.fail("Expired session must not refresh")
    )
    request = SimpleNamespace(
        cookies={browser.COOKIE: sid},
        method="GET",
        app=SimpleNamespace(state=SimpleNamespace(settings=env.settings)),
    )
    from foodbridge.domain.errors import AppError

    with pytest.raises(AppError) as error:
        browser.browser_subject(request)
    assert error.value.status == 401
    assert env.redis.get(browser.key("session", sid)) is None


def test_logout_racing_refresh_cannot_resurrect_session(browser_env, monkeypatch):
    env = browser_env
    sid = "logout-race"
    env.redis.set(
        browser.key("session", sid),
        json.dumps(
            {
                "subject": "verified-user",
                "expires_at": 0,
                "absolute_expiry": time.time() + 300,
                "refresh_token": "private",
            }
        ),
    )

    def post(*args, **kwargs):
        env.redis.delete(browser.key("session", sid))
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "access_token": env.token("foodbridge-api"),
                "token_type": "Bearer",
                "expires_in": 300,
            },
        )

    monkeypatch.setattr(browser.httpx, "post", post)
    request = SimpleNamespace(
        cookies={browser.COOKIE: sid},
        method="GET",
        app=SimpleNamespace(state=SimpleNamespace(settings=env.settings)),
    )
    from foodbridge.domain.errors import AppError

    with pytest.raises(AppError) as error:
        browser.browser_subject(request)
    assert error.value.status == 401
    assert env.redis.get(browser.key("session", sid)) is None


def test_multi_audience_id_token_requires_authorized_party(browser_env, monkeypatch):
    env = browser_env
    state, saved = login_state(env)
    monkeypatch.setattr(
        browser.httpx,
        "post",
        lambda *a, **kw: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "access_token": env.token("foodbridge-api"),
                "id_token": env.token(["foodbridge-web", "other-client"], nonce=saved["nonce"]),
                "token_type": "Bearer",
                "expires_in": 300,
            },
        ),
    )
    assert env.client.get(f"/api/v1/auth/callback?state={state}&code=code").status_code == 400
    assert env.client.cookies.get(browser.COOKIE) is None


def test_logout_clears_local_session_during_provider_outage(browser_env, monkeypatch):
    from foodbridge.domain.errors import AppError

    env = browser_env
    sid = "provider-down-session"
    env.redis.set(browser.key("session", sid), json.dumps({"refresh_token": "private"}))
    env.client.cookies.set(browser.COOKIE, sid, domain="testserver.local", path="/")

    def unavailable(*args):
        raise AppError("identity_provider_unavailable", "Unavailable.", 503)

    monkeypatch.setattr(browser, "metadata", unavailable)
    response = env.client.post("/api/v1/auth/logout", headers={"Origin": env.settings.public_url})
    assert response.status_code == 200
    assert env.redis.get(browser.key("session", sid)) is None
    assert env.client.cookies.get(browser.COOKIE) is None
