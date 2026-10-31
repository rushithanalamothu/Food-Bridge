"""Idempotently provision one synthetic local donor. Never modifies an existing membership."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from foodbridge.auth.identity import DEMO_SUBJECT
from foodbridge.db.models import Membership, Organization, User
from foodbridge.db.session import session_factory
from foodbridge.settings import Settings


def seed(settings: Settings) -> None:
    if settings.environment != "local" or not settings.enable_local_intake_demo:
        raise SystemExit("Set FOODBRIDGE_ENABLE_LOCAL_INTAKE_DEMO=true in local development only.")
    org_id = uuid5(NAMESPACE_URL, "foodbridge:local-demo:kitchen")
    user_id = uuid5(NAMESPACE_URL, DEMO_SUBJECT)
    with session_factory(settings.database_url).begin() as session:
        if session.get(Organization, org_id) is None:
            session.add(
                Organization(
                    id=org_id,
                    name="Evergreen Kitchen (demo)",
                    address="210 Market Street, San Jose, CA (synthetic)",
                    timezone="America/Los_Angeles",
                    location="SRID=4326;POINT(-121.89 37.332)",
                    active=True,
                )
            )
            session.flush()
        if session.scalar(select(User).where(User.oidc_subject == DEMO_SUBJECT)) is None:
            session.add(
                User(id=user_id, oidc_subject=DEMO_SUBJECT, display_name="Maya (demo)", active=True)
            )
            session.flush()
            session.add(Membership(user_id=user_id, organization_id=org_id, role="donor"))
    print("Local demo donor ready. No real organizations, tokens or notifications were created.")


if __name__ == "__main__":
    seed(Settings())
