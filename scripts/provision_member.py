"""Trusted server-admin CLI: bind an existing org to a verified OIDC subject/contact.

Not a public endpoint. Never derives roles or contact verification from browser claims.
"""

import argparse
from uuid import UUID, uuid4

from sqlalchemy import select

from foodbridge.agents.intake.service import utcnow
from foodbridge.db.models import Membership, Organization, User
from foodbridge.db.session import session_factory
from foodbridge.db.workflow_models import NotificationContact
from foodbridge.integrations.email import valid_email
from foodbridge.settings import Settings


def provision(settings, *, subject, organization_id, role, display_name, email=None, consent=False):
    if role not in {"donor", "recipient", "driver", "operator"} or not subject.strip():
        raise ValueError("invalid subject/role")
    if email:
        valid_email(email)
        if not consent:
            raise ValueError(
                "Contact requires administrator attestation of address ownership and consent"
            )
    with session_factory(settings.database_url).begin() as session:
        org = session.get(Organization, organization_id)
        if org is None or not org.active:
            raise ValueError("Existing active organization required")
        user = session.scalar(select(User).where(User.oidc_subject == subject))
        if user is None:
            user = User(id=uuid4(), oidc_subject=subject, display_name=display_name, active=True)
            session.add(user)
            session.flush()
        if not user.active:
            raise ValueError("Inactive user cannot be provisioned")
        if session.get(Membership, (user.id, org.id, role)) is None:
            session.add(Membership(user_id=user.id, organization_id=org.id, role=role))
        if email:
            contact = session.get(NotificationContact, user.id, with_for_update=True)
            if contact:
                contact.email, contact.enabled, contact.updated_at = email, True, utcnow()
                contact.version += 1
            else:
                session.add(
                    NotificationContact(
                        user_id=user.id, email=email, enabled=True, updated_at=utcnow()
                    )
                )
        return user.id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--organization-id", required=True, type=UUID)
    parser.add_argument(
        "--role", required=True, choices=["donor", "recipient", "driver", "operator"]
    )
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--email")
    parser.add_argument("--attest-verified-contact-and-consent", action="store_true")
    args = parser.parse_args()
    identifier = provision(
        Settings(),
        subject=args.subject,
        organization_id=args.organization_id,
        role=args.role,
        display_name=args.display_name,
        email=args.email,
        consent=args.attest_verified_contact_and_consent,
    )
    print(f"Provisioned membership for user {identifier}; contact values omitted.")


if __name__ == "__main__":
    main()
