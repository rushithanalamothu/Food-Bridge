"""Add local-only synthetic actors with routable San Jose locations; never reset data."""

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from scripts.seed_intake_demo import seed as seed_donor
from sqlalchemy import select
from sqlalchemy.engine import make_url

from foodbridge.agents.intake.service import utcnow
from foodbridge.db.models import Membership, Organization, User
from foodbridge.db.session import session_factory
from foodbridge.db.workflow_models import Capacity, Driver, RecipientState
from foodbridge.domain.contracts import Location, PickupWindow, RecipientProfile
from foodbridge.domain.intake import DriverFacts
from foodbridge.settings import Settings

RECIPIENTS = (
    Location(address="Synthetic San Jose receiver A", latitude=37.3348, longitude=-121.8881),
    Location(address="Synthetic San Jose receiver B", latitude=37.3290, longitude=-121.8840),
)
DRIVER_ORIGIN = Location(
    address="Synthetic San Jose driver origin", latitude=37.3330, longitude=-121.9000
)


def recipient_id(index):
    return uuid5(NAMESPACE_URL, f"foodbridge:matching-demo:recipient:{index}")


def seed(settings: Settings):
    host = make_url(settings.database_url).host
    if (
        settings.environment != "local"
        or not settings.enable_local_matching_demo
        or host not in {"localhost", "127.0.0.1", "db"}
    ):
        raise SystemExit("Local matching fixture requires the matching demo and a local database.")
    seed_donor(settings)
    now = utcnow()
    window = PickupWindow(start=now - timedelta(days=1), end=now + timedelta(days=30))
    donor_id = uuid5(NAMESPACE_URL, "foodbridge:local-demo:kitchen")
    actors = [
        ("recipient", recipient_id(index), location) for index, location in enumerate(RECIPIENTS)
    ] + [("driver", uuid5(NAMESPACE_URL, "foodbridge:matching-demo:driver"), DRIVER_ORIGIN)]
    with session_factory(settings.database_url).begin() as session:
        for role, organization_id, location in actors:
            if session.get(Organization, organization_id) is None:
                session.add(
                    Organization(
                        id=organization_id,
                        name=location.address,
                        address=location.address,
                        timezone=location.timezone,
                        location=f"SRID=4326;POINT({location.longitude} {location.latitude})",
                        active=True,
                    )
                )
                session.flush()
            subject = f"foodbridge:matching-demo:{role}"
            user = session.scalar(select(User).where(User.oidc_subject == subject))
            if user is None:
                user = User(
                    id=uuid5(NAMESPACE_URL, subject),
                    oidc_subject=subject,
                    display_name=f"Synthetic {role}",
                    active=True,
                )
                session.add(user)
                session.flush()
            if session.get(Membership, (user.id, organization_id, role)) is None:
                session.add(Membership(user_id=user.id, organization_id=organization_id, role=role))
            if role == "recipient" and session.get(RecipientState, organization_id) is None:
                profile = RecipientProfile(
                    organization_id=organization_id,
                    location=location,
                    accepted_categories=["prepared_meals", "produce", "bakery"],
                    accepted_storage=["chilled", "ambient"],
                    available_capacity_kg_by_storage={"chilled": 40, "ambient": 40},
                    rejected_allergens=["peanut"],
                    required_dietary_tags=["vegetarian"],
                    receiving_window=window,
                    version=1,
                )
                session.add(
                    RecipientState(
                        organization_id=organization_id,
                        profile=profile.model_dump(mode="json"),
                        verified=True,
                    )
                )
                for storage in profile.accepted_storage:
                    session.add(
                        Capacity(
                            organization_id=organization_id,
                            storage=storage,
                            reported_free_kg=40,
                        )
                    )
            if (
                role == "driver"
                and session.scalar(select(Driver.id).where(Driver.user_id == user.id)) is None
            ):
                identifier = uuid5(NAMESPACE_URL, "foodbridge:matching-demo:driver-record")
                facts = DriverFacts(
                    id=identifier,
                    available=True,
                    window=window,
                    capacity_kg=50,
                    storage_types=["ambient", "chilled"],
                    to_pickup_time_s=0,
                )
                session.add(
                    Driver(
                        id=identifier,
                        user_id=user.id,
                        organization_id=organization_id,
                        facts=facts.model_dump(mode="json"),
                    )
                )
        operator_subject = "foodbridge:matching-demo:operator"
        operator = session.scalar(select(User).where(User.oidc_subject == operator_subject))
        if operator is None:
            operator = User(
                id=uuid5(NAMESPACE_URL, operator_subject),
                oidc_subject=operator_subject,
                display_name="Synthetic operator",
                active=True,
            )
            session.add(operator)
            session.flush()
        if session.get(Membership, (operator.id, donor_id, "operator")) is None:
            session.add(Membership(user_id=operator.id, organization_id=donor_id, role="operator"))
    print("Local matching actors ready; existing capacities and profiles were preserved.")


if __name__ == "__main__":
    seed(Settings())
