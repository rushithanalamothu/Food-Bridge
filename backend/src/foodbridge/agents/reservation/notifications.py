"""Stable notification effect IDs; an ambiguous send may duplicate at non-idempotent providers."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_, select

from foodbridge.agents.intake.service import utcnow
from foodbridge.db.session import session_factory
from foodbridge.db.workflow_models import Notification
from foodbridge.integrations.workflow import DependencyUnavailable


class SandboxNotifications:
    """Local receipt only: no email/SMS leaves the machine."""

    def send(self, *, notification_id, destination_id, template):
        return f"sandbox:{notification_id}"


class DisabledNotifications:
    def send(self, **kwargs):
        raise DependencyUnavailable("notification_service_unavailable")


def notification_provider(settings):
    return (
        SandboxNotifications()
        if settings.notification_mode == "sandbox"
        else DisabledNotifications()
    )


def deliver_pending(database_url, provider, clock=utcnow, limit=20):
    sessions = session_factory(database_url)
    delivered = 0
    for _ in range(limit):
        now, token = clock(), uuid4()
        with sessions.begin() as session:
            row = session.scalar(
                select(Notification)
                .where(
                    Notification.status.in_(["pending", "sending"]),
                    Notification.next_attempt_at <= now,
                    or_(Notification.lease_until.is_(None), Notification.lease_until <= now),
                )
                .order_by(Notification.next_attempt_at, Notification.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                break
            if row.attempts >= 3:
                row.status, row.lease_until = "failed", None
                continue
            row.status, row.lease_token = "sending", token
            row.lease_until, row.attempts = now + timedelta(seconds=30), row.attempts + 1
            identifier, destination, template = row.id, row.user_id, row.template
        failed = False
        try:
            provider_id = provider.send(
                notification_id=str(identifier), destination_id=str(destination), template=template
            )
            if provider_id is not None and (
                not isinstance(provider_id, str) or len(provider_id) > 200
            ):
                raise ValueError("invalid_provider_receipt")
        except Exception:
            # Provider exceptions may contain addresses/keys; persist only failure state.
            failed, provider_id = True, None
        with sessions.begin() as session:
            row = session.get(Notification, identifier, with_for_update=True)
            if row.lease_token != token:
                continue
            row.lease_until = None
            if failed:
                row.status = "failed" if row.attempts >= 3 else "pending"
                row.next_attempt_at = clock() + timedelta(seconds=min(30, 2**row.attempts))
            else:
                row.status, row.provider_id = "sent", provider_id
                delivered += 1
    return delivered
