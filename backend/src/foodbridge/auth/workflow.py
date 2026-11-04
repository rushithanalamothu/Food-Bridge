"""Role selection narrows verified memberships; client headers never grant membership."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from foodbridge.auth.identity import DEMO_SUBJECT, verified_subject
from foodbridge.db.models import Membership, Organization, User
from foodbridge.db.session import session_factory
from foodbridge.domain.errors import AppError
from foodbridge.domain.workflow import Actor


def current_actor(
    request: Request,
    _credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ],
) -> Actor:
    settings = request.app.state.settings
    authorization = request.headers.get("authorization", "")
    selected_role = request.headers.get("x-foodbridge-role")
    selected_org = request.headers.get("x-organization-id")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AppError("invalid_token", "A bearer access token is required.", 401)
        subject = verified_subject(token, settings)
    elif settings.environment == "local" and settings.enable_local_workflow_demo:
        role = selected_role or "donor"
        subject = DEMO_SUBJECT if role == "donor" else f"foodbridge:workflow-demo:{role}"
    else:
        raise AppError("authentication_required", "Sign in through the gateway.", 401)
    if selected_role and selected_role not in {"donor", "recipient", "driver", "operator"}:
        raise AppError("invalid_role", "Unknown role.", 400)
    try:
        org_id = UUID(selected_org) if selected_org else None
    except ValueError as exc:
        raise AppError("invalid_organization", "Invalid organization selector.", 400) from exc
    with session_factory(settings.database_url)() as session:
        query = (
            select(Membership)
            .join(User, User.id == Membership.user_id)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(
                User.oidc_subject == subject, User.active.is_(True), Organization.active.is_(True)
            )
        )
        if selected_role:
            query = query.where(Membership.role == selected_role)
        if org_id:
            query = query.where(Membership.organization_id == org_id)
        rows = list(session.scalars(query))
        if not rows:
            raise AppError("membership_required", "An active membership is required.", 403)
        if len(rows) != 1:
            raise AppError("membership_selection_required", "Select an organization and role.", 409)
        return Actor(
            user_id=rows[0].user_id, organization_id=rows[0].organization_id, role=rows[0].role
        )
