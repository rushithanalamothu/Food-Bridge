"""OIDC authorization-code + PKCE BFF. Tokens stay in Redis, never browser storage."""

import base64
import hashlib
import json
import secrets
import time
from functools import lru_cache
from typing import Literal
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select

from foodbridge.db.models import Membership, Organization, User
from foodbridge.db.session import session_factory
from foodbridge.domain.errors import AppError
from foodbridge.domain.workflow import BrowserSessionRead

router = APIRouter(prefix="/api/v1/auth", tags=["browser authentication"])
COOKIE = "foodbridge_session"
LOGIN_COOKIE = "foodbridge_login"


def fail(code="session_expired", status=401):
    raise AppError(code, "Sign in again or contact your administrator.", status)


def store(settings):
    return Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=3)


def key(kind, value):
    return "foodbridge:auth:" + kind + ":" + hashlib.sha256(value.encode()).hexdigest()


def csrf(request):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin", "")
        if origin not in {
            request.app.state.settings.public_url.rstrip("/"),
            *request.app.state.settings.cors_origins,
        }:
            fail("origin_required", 403)


def backchannel(url, settings):
    if not settings.oidc_backchannel_base_url:
        return url
    public, internal, target = map(
        urlsplit, (settings.oidc_issuer, settings.oidc_backchannel_base_url, url)
    )
    if (target.scheme, target.netloc) != (public.scheme, public.netloc):
        fail("invalid_identity_endpoint", 503)
    return urlunsplit((internal.scheme, internal.netloc, target.path, target.query, ""))


@lru_cache(maxsize=8)
def discovery(issuer, internal):
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    if internal:
        source, target = urlsplit(url), urlsplit(internal)
        url = urlunsplit((target.scheme, target.netloc, source.path, "", ""))
    try:
        response = httpx.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data["issuer"].rstrip("/") != issuer.rstrip("/"):
            raise ValueError("issuer mismatch")
        expected = urlsplit(issuer)
        for name in (
            "authorization_endpoint",
            "token_endpoint",
            "revocation_endpoint",
            "end_session_endpoint",
        ):
            if data.get(name):
                endpoint = urlsplit(data[name])
                if (
                    (endpoint.scheme, endpoint.netloc) != (expected.scheme, expected.netloc)
                    or endpoint.username
                    or endpoint.password
                    or endpoint.fragment
                ):
                    raise ValueError("untrusted endpoint")
        return data
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        fail("identity_provider_unavailable", 503)


def metadata(settings):
    if not settings.browser_auth_enabled:
        fail("browser_auth_not_configured", 503)
    return discovery(settings.oidc_issuer, settings.oidc_backchannel_base_url)


def exchange(settings, data):
    payload = {"client_id": settings.oidc_client_id, **data}
    if settings.oidc_client_secret:
        payload["client_secret"] = settings.oidc_client_secret.get_secret_value()
    try:
        response = httpx.post(
            backchannel(metadata(settings)["token_endpoint"], settings), data=payload, timeout=8
        )
        response.raise_for_status()
        result = response.json()
        from foodbridge.auth.identity import verified_subject

        subject = verified_subject(result["access_token"], settings)
        if str(result.get("token_type", "")).lower() != "bearer":
            raise ValueError("invalid token type")
        lifetime = int(result["expires_in"])
        if lifetime <= 0:
            raise ValueError("invalid token lifetime")
        return result, subject, lifetime
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        fail()


def browser_subject(request):
    """An invalid session cannot fall back to a synthetic identity."""
    sid = request.cookies.get(request.app.state.settings.browser_cookie_name)
    if not sid:
        return None
    if not request.app.state.settings.browser_auth_enabled:
        fail()
    csrf(request)
    settings = request.app.state.settings
    try:
        redis = store(settings)
        saved = redis.get(key("session", sid))
        if not saved:
            fail()
        session = json.loads(saved)
        if session["absolute_expiry"] <= time.time():
            redis.delete(key("session", sid))
            fail()
        if session["expires_at"] <= time.time() + 30:
            lock = redis.lock(key("refresh", sid), timeout=60, blocking_timeout=2)
            if not lock.acquire():
                fail("session_refresh_busy", 503)
            try:
                current = redis.get(key("session", sid))
                if not current:
                    fail()
                session = json.loads(current)
                if session["expires_at"] <= time.time() + 30:
                    if not session.get("refresh_token"):
                        fail()
                    tokens, subject, lifetime = exchange(
                        settings,
                        {"grant_type": "refresh_token", "refresh_token": session["refresh_token"]},
                    )
                    if subject != session["subject"]:
                        redis.delete(key("session", sid))
                        fail()
                    session.update(
                        access_token=tokens["access_token"],
                        refresh_token=tokens.get("refresh_token", session["refresh_token"]),
                        expires_at=time.time() + lifetime,
                    )
                    # XX prevents logout racing refresh from resurrecting a session.
                    ttl = int(session["absolute_expiry"] - time.time())
                    if ttl <= 0 or not redis.set(
                        key("session", sid), json.dumps(session), ex=ttl, xx=True
                    ):
                        fail()
            finally:
                lock.release()
        from foodbridge.auth.identity import verified_subject

        return verified_subject(session["access_token"], settings)
    except RedisError:
        fail("session_store_unavailable", 503)
    except (ValueError, KeyError, TypeError):
        fail()


def cookie(response, name, value, settings, age):
    response.set_cookie(
        name,
        value,
        max_age=age,
        httponly=True,
        secure=settings.environment != "local",
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


@router.get("/login", include_in_schema=False)
def login(request: Request, return_to: str = "/", intent: Literal["login", "register"] = "login"):
    settings = request.app.state.settings
    info = metadata(settings)
    if intent == "register" and not settings.browser_registration_enabled:
        fail("registration_unavailable", 403)
    if return_to not in {"/", "/donor", "/recipient", "/driver", "/operations"}:
        return_to = "/"
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    saved = {"nonce": nonce, "verifier": verifier, "return_to": return_to}
    try:
        store(settings).set(key("login", state), json.dumps(saved), ex=settings.browser_login_ttl_s)
    except RedisError:
        fail("session_store_unavailable", 503)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    params = {
        "client_id": settings.oidc_client_id,
        "response_type": "code",
        "scope": "openid profile",
        "redirect_uri": settings.public_url.rstrip("/") + "/api/v1/auth/callback",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if intent == "register":
        params["prompt"] = "create"
    response = RedirectResponse(
        info["authorization_endpoint"] + "?" + urlencode(params), status_code=302
    )
    cookie(response, LOGIN_COOKIE, state, settings, settings.browser_login_ttl_s)
    return response


@router.get("/callback", include_in_schema=False)
def callback(request: Request, state: str = "", code: str = "", error: str = ""):
    try:
        return complete_callback(request, state, code, error)
    except AppError:
        if "text/html" not in request.headers.get("accept", ""):
            raise
        # A stale email/login tab must not strand a person on an API JSON error.
        # All state/nonce/PKCE/token checks remain in complete_callback.
        response = RedirectResponse("/auth/error", status_code=303)
        response.delete_cookie(LOGIN_COOKIE, path="/")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


def complete_callback(request: Request, state: str, code: str, error: str):
    settings = request.app.state.settings
    metadata(settings)
    if (
        error
        or not state
        or len(state) > 200
        or len(code) > 4096
        or not code
        or not secrets.compare_digest(request.cookies.get(LOGIN_COOKIE, ""), state)
    ):
        fail("invalid_login_state", 400)
    try:
        redis = store(settings)
        raw = redis.getdel(key("login", state))
        if not raw:
            fail("invalid_login_state", 400)
        saved = json.loads(raw)
        tokens, subject, lifetime = exchange(
            settings,
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": saved["verifier"],
                "redirect_uri": settings.public_url.rstrip("/") + "/api/v1/auth/callback",
            },
        )
        from foodbridge.auth.identity import jwks_client

        signing = jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(tokens["id_token"])
        claims = jwt.decode(
            tokens["id_token"],
            signing.key,
            algorithms=["RS256"],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iat", "sub", "nonce"]},
        )
        if claims["sub"] != subject or not secrets.compare_digest(claims["nonce"], saved["nonce"]):
            fail("invalid_login_token", 400)
        multiple_audiences = isinstance(claims["aud"], list) and len(claims["aud"]) > 1
        if claims.get("azp", settings.oidc_client_id) != settings.oidc_client_id or (
            multiple_audiences and claims.get("azp") != settings.oidc_client_id
        ):
            fail("invalid_login_token", 400)
        sid = secrets.token_urlsafe(48)
        session = {
            "subject": subject,
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": time.time() + lifetime,
            "absolute_expiry": time.time() + settings.browser_session_ttl_s,
        }
        redis.set(key("session", sid), json.dumps(session), ex=settings.browser_session_ttl_s)
        old = request.cookies.get(request.app.state.settings.browser_cookie_name)
        if old:
            redis.delete(key("session", old))
    except RedisError:
        fail("session_store_unavailable", 503)
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        fail("invalid_login_token", 400)
    response = RedirectResponse(saved["return_to"], status_code=303)
    cookie(response, settings.browser_cookie_name, sid, settings, settings.browser_session_ttl_s)
    response.delete_cookie(LOGIN_COOKIE, path="/")
    return response


@router.post("/logout")
def logout(request: Request):
    csrf(request)
    settings = request.app.state.settings
    sid = request.cookies.get(request.app.state.settings.browser_cookie_name)
    try:
        if sid:
            redis = store(settings)
            raw = redis.getdel(key("session", sid))
            if raw and settings.browser_auth_enabled:
                try:
                    session = json.loads(raw)
                    endpoint = metadata(settings).get("revocation_endpoint")
                    if endpoint and session.get("refresh_token"):
                        payload = {
                            "client_id": settings.oidc_client_id,
                            "token": session["refresh_token"],
                            "token_type_hint": "refresh_token",
                        }
                        if settings.oidc_client_secret:
                            payload["client_secret"] = (
                                settings.oidc_client_secret.get_secret_value()
                            )
                        httpx.post(backchannel(endpoint, settings), data=payload, timeout=5)
                except (AppError, httpx.HTTPError, ValueError, KeyError, TypeError):
                    # Application logout survives identity-provider/revocation outages.
                    pass
    except RedisError:
        fail("session_store_unavailable", 503)
    response = JSONResponse({"signed_out": True})
    response.delete_cookie(settings.browser_cookie_name, path="/")
    response.delete_cookie(LOGIN_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/session", response_model=BrowserSessionRead)
def session_info(request: Request):
    from foodbridge.auth.identity import request_subject

    settings = request.app.state.settings
    try:
        subject = request_subject(request)
    except AppError as error:
        if error.status != 401 or not settings.browser_auth_enabled:
            raise
        # Session discovery must let an expired browser start a fresh login.
        # Protected endpoints continue rejecting the stale credential.
        response = JSONResponse(
            {
                "authenticated": False,
                "login_enabled": True,
                "registration_enabled": settings.browser_registration_enabled,
                "memberships": [],
            },
            headers={"Cache-Control": "no-store"},
        )
        response.delete_cookie(COOKIE, path="/")
        return response
    mode = "oidc"
    if (
        subject is None
        and settings.environment == "local"
        and settings.enable_local_workflow_demo
        and not settings.browser_auth_enabled
    ):
        from foodbridge.auth.identity import DEMO_SUBJECT

        subject, mode = DEMO_SUBJECT, "local_demo"
    if subject is None:
        return JSONResponse(
            {
                "authenticated": False,
                "login_enabled": settings.browser_auth_enabled,
                "registration_enabled": settings.browser_auth_enabled
                and settings.browser_registration_enabled,
                "memberships": [],
            },
            headers={"Cache-Control": "no-store"},
        )
    with session_factory(settings.database_url)() as session:
        query = (
            select(Membership, Organization, User)
            .join(Organization, Membership.organization_id == Organization.id)
            .join(User, Membership.user_id == User.id)
            .where(
                User.oidc_subject == subject, User.active.is_(True), Organization.active.is_(True)
            )
        )
        memberships = [
            {"organization_id": str(org.id), "organization_name": org.name, "role": membership.role}
            for membership, org, _ in session.execute(query)
        ]
    return JSONResponse(
        {
            "authenticated": True,
            "mode": mode,
            "login_enabled": settings.browser_auth_enabled,
            "registration_enabled": settings.browser_auth_enabled
            and settings.browser_registration_enabled,
            "memberships": memberships,
        },
        headers={"Cache-Control": "no-store"},
    )
