"""Bounded SMTP adapter with consented destinations; no provider I/O inside transactions."""

import re
import smtplib
import ssl
from email.message import EmailMessage
from uuid import UUID

from sqlalchemy import select

from foodbridge.db.models import Membership, Organization, OutboxEvent, User
from foodbridge.db.session import session_factory
from foodbridge.db.workflow_models import Notification, NotificationContact


def valid_email(value):
    if (
        not isinstance(value, str)
        or len(value) > 254
        or not re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}",
            value,
        )
    ):
        raise ValueError("invalid_email")
    return value


class SMTPNotifications:
    # Covers bounded SMTP connect/TLS/auth/send/quit and the worker hard limit.
    lease_seconds = 90

    def __init__(self, settings, *, smtp_factory=None):
        self.settings = settings
        self.sessions = session_factory(settings.database_url)
        self.smtp_factory = smtp_factory

    def destination(self, notification_id, destination_id):
        with self.sessions() as session:
            user = session.get(User, UUID(destination_id))
            contact = session.get(NotificationContact, UUID(destination_id))
            row = session.get(Notification, UUID(notification_id))
            event = session.get(OutboxEvent, row.event_id) if row else None
            if (
                not user
                or not user.active
                or not contact
                or not contact.enabled
                or not event
                or row.user_id != user.id
            ):
                raise ValueError("notification_destination_unavailable")
            memberships = {
                (str(org), role)
                for org, role in session.execute(
                    select(Membership.organization_id, Membership.role)
                    .join(Organization, Organization.id == Membership.organization_id)
                    .where(Membership.user_id == user.id, Organization.active.is_(True))
                )
            }
            if not any(
                target.get("user_id") == str(user.id)
                or (target.get("organization_id"), target.get("role")) in memberships
                for target in event.audience
            ):
                raise ValueError("notification_destination_not_authorized")
            return valid_email(contact.email)

    def send(self, *, notification_id, destination_id, template):
        settings = self.settings
        destination = self.destination(notification_id, destination_id)
        if (
            settings.smtp_allowed_domains
            and destination.rsplit("@", 1)[1].lower() not in settings.smtp_allowed_domains
        ):
            raise ValueError("notification_domain_not_allowed")
        message = EmailMessage()
        message["From"] = valid_email(settings.smtp_sender)
        message["To"] = destination
        message["Subject"] = "FoodBridge: donation status updated"
        message["Message-ID"] = f"<{UUID(notification_id)}@foodbridge.notifications>"
        # Do not include donor descriptions, addresses or model text in email.
        message.set_content(
            f"A FoodBridge donation you follow has an update.\nEvent: {template}\n"
            f"Sign in to view current details: {settings.public_url}\n"
        )
        factory = self.smtp_factory or (
            smtplib.SMTP_SSL if settings.smtp_security == "tls" else smtplib.SMTP
        )
        kwargs = {"timeout": settings.smtp_timeout_s}
        if settings.smtp_security == "tls":
            kwargs["context"] = ssl.create_default_context()
        with factory(settings.smtp_host, settings.smtp_port, **kwargs) as smtp:
            if settings.smtp_security == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            refused = smtp.send_message(message)
            if refused:
                raise ValueError("notification_refused")
        # This records SMTP server acceptance, not proof the recipient read the email.
        return str(message["Message-ID"])
