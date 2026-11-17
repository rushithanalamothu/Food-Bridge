"""Local-only Keycloak/Mailpit verification identities. Never runs on shared hosts."""

from uuid import NAMESPACE_URL, uuid5

from provision_member import provision
from seed_workflow_demo import seed
from sqlalchemy import select

from foodbridge.agents.intake.service import utcnow
from foodbridge.db.models import User
from foodbridge.db.session import session_factory
from foodbridge.db.workflow_models import Driver, NotificationContact
from foodbridge.settings import Settings


def run(settings):
    if (
        settings.environment != "local"
        or settings.smtp_host != "mailpit"
        or settings.smtp_allowed_domains != ["example.test"]
    ):
        raise SystemExit("Restricted to local Mailpit verification; no real addresses permitted.")
    seed(settings)
    oidc_user_id = None
    for role in ("donor", "recipient", "driver", "operator"):
        org = uuid5(
            NAMESPACE_URL,
            "foodbridge:local-demo:kitchen"
            if role in {"donor", "operator"}
            else f"foodbridge:workflow-demo:org:{role}",
        )
        oidc_user_id = provision(
            settings,
            subject="11111111-1111-4111-8111-111111111111",
            organization_id=org,
            role=role,
            display_name="Synthetic Keycloak user",
            email="tej@example.test",
            consent=True,
        )
    with session_factory(settings.database_url).begin() as session:
        # Associate the synthetic assignment driver with the real OIDC test identity.
        # This stack is isolated; the ordinary demo stack/identities are untouched.
        driver = session.scalar(
            select(Driver).where(
                Driver.id == uuid5(NAMESPACE_URL, "foodbridge:workflow-demo:driver-record")
            )
        )
        driver.user_id = oidc_user_id
        for user in session.scalars(
            select(User).where(
                User.oidc_subject.in_(
                    [
                        "foodbridge:local-demo:maya",
                        "foodbridge:workflow-demo:recipient",
                        "foodbridge:workflow-demo:driver",
                    ]
                )
            )
        ):
            if session.get(NotificationContact, user.id) is None:
                session.add(
                    NotificationContact(
                        user_id=user.id,
                        email=f"{user.id}@example.test",
                        enabled=True,
                        updated_at=utcnow(),
                    )
                )
    print("Provisioned synthetic OIDC memberships and Mailpit-only contacts.")


if __name__ == "__main__":
    run(Settings())
