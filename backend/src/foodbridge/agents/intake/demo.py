"""Clearly synthetic candidate facts for the opt-in local workflow. Never live routing data."""

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from foodbridge.domain.contracts import PickupWindow, RecipientProfile
from foodbridge.domain.intake import (
    DriverFacts,
    EligibilityBatch,
    EligibilityCandidate,
    IntakeDonationRead,
    RouteFacts,
)


def demo_batch(snapshot: IntakeDonationRead, now: datetime) -> EligibilityBatch:
    location = snapshot.donation.pickup_location
    window = PickupWindow(
        start=now, end=max(now + timedelta(hours=12), snapshot.donation.safe_use_by)
    )
    candidates = []
    for index, capacity in enumerate((18, 5)):
        recipient = RecipientProfile(
            organization_id=uuid5(NAMESPACE_URL, f"foodbridge/demo-recipient/{index}"),
            location=location,
            accepted_categories=["prepared_meals", "produce", "bakery"],
            accepted_storage=["ambient", "chilled"],
            available_capacity_kg_by_storage={"ambient": capacity, "chilled": capacity},
            rejected_allergens=["peanut"],
            required_dietary_tags=["vegetarian"],
            receiving_window=window.model_copy(),
            version=1,
        )
        candidates.append(
            EligibilityCandidate(
                recipient=recipient,
                active_and_verified=True,
                route=RouteFacts(
                    distance_m=5150, travel_time_s=840, calculated_at=now, source="synthetic"
                ),
                driver=DriverFacts(
                    id=uuid5(NAMESPACE_URL, "foodbridge/demo-driver"),
                    available=True,
                    window=window.model_copy(),
                    capacity_kg=40,
                    storage_types=["ambient", "chilled"],
                    to_pickup_time_s=300,
                ),
            )
        )
    return EligibilityBatch(
        donation_id=snapshot.donation.id,
        expected_donation_version=snapshot.donation.version,
        candidates=candidates,
        synthetic=True,
    )
