"""JWT verification selects a server-managed membership; no browser-provided actor IDs."""

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select

from foodbridge.db.models import Membership, Organization, User
from foodbridge.db.session import session_factory
from foodbridge.domain.contracts import Location
from foodbridge.domain.errors import AppError
from foodbridge.domain.intake import DonorIdentity
from foodbridge.settings import Settings

DEMO_SUBJECT = "foodbridge:local-demo:maya"


@lru_cache(maxsize=4)
def jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=5)


def verified_subject(token: str, settings: Settings) -> str:
    if not all((settings.oidc_jwks_url, settings.oidc_issuer, settings.oidc_audience)):
        raise AppError(
            "auth_not_configured", "The gateway identity provider is not configured.", 503
        )
    try:
        signing_key = jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
        if not isinstance(claims["sub"], str) or not claims["sub"].strip():
            raise jwt.InvalidTokenError("invalid subject")
        return claims["sub"]
    except (jwt.InvalidTokenError, jwt.PyJWKClientError) as exc:
        raise AppError("invalid_token", "Your session is invalid or expired.", 401) from exc


def current_donor(
    request: Request,
    _credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ],
) -> DonorIdentity:
    settings = request.app.state.settings
    authorization = request.headers.get("authorization", "")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AppError("invalid_token", "A bearer access token is required.", 401)
        subject = verified_subject(token, settings)
        mode = "oidc"
    elif settings.enable_local_intake_demo and settings.environment == "local":
        # This opt-in local-only mode never chooses an identity from client input.
        subject, mode = DEMO_SUBJECT, "local_demo"
    else:
        raise AppError("authentication_required", "Sign in through the gateway to post food.", 401)
    with session_factory(settings.database_url)() as session:
        rows = session.execute(
            select(
                User,
                Organization,
                func.ST_Y(cast(Organization.location, Geometry("POINT", srid=4326))),
                func.ST_X(cast(Organization.location, Geometry("POINT", srid=4326))),
            )
            .join(Membership, Membership.user_id == User.id)
            .join(Organization, Membership.organization_id == Organization.id)
            .where(
                User.oidc_subject == subject,
                User.active.is_(True),
                Organization.active.is_(True),
                Membership.role == "donor",
            )
        ).all()
        if not rows:
            raise AppError(
                "donor_membership_required", "An active donor membership is required.", 403
            )
        if len(rows) != 1:
            raise AppError(
                "organization_selection_required",
                "Select one donor membership through the gateway.",
                409,
            )
        user, org, latitude, longitude = rows[0]
        return DonorIdentity(
            user_id=user.id,
            organization_id=org.id,
            organization_name=org.name,
            display_name=user.display_name,
            mode=mode,
            pickup_location=Location(
                address=org.address, latitude=latitude, longitude=longitude, timezone=org.timezone
            ),
        )
