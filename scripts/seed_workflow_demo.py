"""Provision explicit local synthetic recipient, driver and operator memberships."""

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from seed_intake_demo import seed as seed_donor
from sqlalchemy import select

from foodbridge.agents.intake.service import utcnow
from foodbridge.db.models import Membership, Organization, User
from foodbridge.db.session import session_factory
from foodbridge.db.workflow_models import Capacity, Driver, RecipientState
from foodbridge.domain.contracts import Location, PickupWindow, RecipientProfile
from foodbridge.domain.intake import DriverFacts
from foodbridge.settings import Settings


def seed(settings):
    if (
        settings.environment != "local"
        or not settings.enable_local_workflow_demo
        or not settings.enable_local_intake_demo
    ):
        raise SystemExit("Enable both local demo flags; never run this on a shared/public host.")
    seed_donor(settings)
    now = utcnow()
    location = Location(address="Synthetic San Jose demo site", latitude=37.332, longitude=-121.89)
    donor_org = uuid5(NAMESPACE_URL, "foodbridge:local-demo:kitchen")
    window = PickupWindow(start=now - timedelta(hours=1), end=now + timedelta(days=1))
    with session_factory(settings.database_url).begin() as session:
        for role in ("recipient", "driver", "operator"):
            org_id = (
                donor_org
                if role == "operator"
                else uuid5(NAMESPACE_URL, f"foodbridge:workflow-demo:org:{role}")
            )
            subject = f"foodbridge:workflow-demo:{role}"
            user_id = uuid5(NAMESPACE_URL, subject)
            if session.get(Organization, org_id) is None:
                session.add(
                    Organization(
                        id=org_id,
                        name=f"Synthetic demo {role}",
                        address=location.address,
                        timezone=location.timezone,
                        location="SRID=4326;POINT(-121.89 37.332)",
                        active=True,
                    )
                )
                session.flush()
            if session.scalar(select(User.id).where(User.oidc_subject == subject)) is None:
                session.add(
                    User(id=user_id, oidc_subject=subject, display_name=f"Demo {role}", active=True)
                )
                session.flush()
                session.add(Membership(user_id=user_id, organization_id=org_id, role=role))
            if role == "recipient" and session.get(RecipientState, org_id) is None:
                profile = RecipientProfile(
                    organization_id=org_id,
                    location=location,
                    accepted_categories=["prepared_meals", "produce", "bakery"],
                    accepted_storage=["ambient", "chilled"],
                    available_capacity_kg_by_storage={"ambient": 200, "chilled": 200},
                    rejected_allergens=["peanut"],
                    required_dietary_tags=["vegetarian"],
                    receiving_window=window,
                    version=1,
                )
                session.add(
                    RecipientState(
                        organization_id=org_id,
                        profile=profile.model_dump(mode="json"),
                        verified=True,
                    )
                )
                for storage in profile.accepted_storage:
                    session.add(
                        Capacity(organization_id=org_id, storage=storage, reported_free_kg=200)
                    )
            if (
                role == "driver"
                and session.scalar(select(Driver.id).where(Driver.user_id == user_id)) is None
            ):
                driver_id = uuid5(NAMESPACE_URL, "foodbridge:workflow-demo:driver-record")
                facts = DriverFacts(
                    id=driver_id,
                    available=True,
                    window=window,
                    capacity_kg=50,
                    storage_types=["ambient", "chilled"],
                    to_pickup_time_s=0,
                )
                session.add(
                    Driver(
                        id=driver_id,
                        user_id=user_id,
                        organization_id=org_id,
                        facts=facts.model_dump(mode="json"),
                    )
                )
    print("Synthetic workflow identities ready. Existing capacity/windows were preserved.")


if __name__ == "__main__":
    seed(Settings())
