"""Application read models and invariant-preserving profile commands; no provider calls."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import exists, select

from foodbridge.agents.intake.service import utcnow
from foodbridge.agents.reservation.service import ReservationService
from foodbridge.db.models import Donation, Organization, StatusHistory
from foodbridge.db.session import session_factory
from foodbridge.db.transactions import enqueue_event
from foodbridge.db.workflow import command, current_profile, require_role, require_version, snapshot
from foodbridge.db.workflow_models import Assignment, Capacity, Driver, MatchOffer, Reservation
from foodbridge.domain.errors import AppError
from foodbridge.domain.workflow import (
    DonationDetail,
    DonationHistoryItem,
    DriverOriginRead,
    OfferRead,
    ReceivingProfileRead,
)


class ApplicationService:
    def __init__(self, database_url, clock=utcnow):
        self.sessions, self.clock = session_factory(database_url), clock

    @staticmethod
    def scope(actor):
        if actor.role in {"donor", "operator"}:
            return Donation.donor_organization_id == actor.organization_id
        if actor.role == "recipient":
            return exists().where(
                MatchOffer.donation_id == Donation.id,
                MatchOffer.recipient_organization_id == actor.organization_id,
            )
        return exists().where(
            Assignment.donation_id == Donation.id,
            Driver.id == Assignment.driver_id,
            Driver.user_id == actor.user_id,
            Driver.organization_id == actor.organization_id,
        )

    def detail(self, actor, identifier):
        with self.sessions() as session:
            row = session.scalar(
                select(Donation).where(Donation.id == identifier, self.scope(actor))
            )
            if row is None:
                raise AppError("not_found", "Donation not found.", 404)
            history = session.scalars(
                select(StatusHistory)
                .where(StatusHistory.donation_id == row.id)
                .order_by(StatusHistory.aggregate_version)
            )
            return DonationDetail(
                donation=snapshot(row, self.clock()),
                history=[
                    DonationHistoryItem(
                        aggregate_version=h.aggregate_version,
                        previous_status=h.previous_status,
                        next_status=h.next_status,
                        reason=h.reason,
                        occurred_at=h.occurred_at,
                    )
                    for h in history
                ],
            )

    @staticmethod
    def profile_view(session, org_id):
        row, profile, capacities = current_profile(session, org_id)
        return ReceivingProfileRead(
            profile=profile,
            verified=row.verified,
            reported_free_kg_by_storage={
                key: float(c.reported_free_kg) for key, c in capacities.items()
            },
            committed_inbound_kg_by_storage={
                key: float(c.committed_inbound_kg) for key, c in capacities.items()
            },
            capacity_versions={key: c.version for key, c in capacities.items()},
        )

    def profile(self, actor):
        require_role(actor, "recipient")
        with self.sessions() as session:
            return self.profile_view(session, actor.organization_id)

    def update_driver_origin(self, actor, body, key, correlation_id):
        require_role(actor, "driver")

        def apply(session, now):
            driver = session.scalar(
                select(Driver)
                .where(
                    Driver.user_id == actor.user_id, Driver.organization_id == actor.organization_id
                )
                .with_for_update()
            )
            if driver is None:
                raise AppError("driver_unavailable", "Driver profile is not provisioned.", 404)
            require_version(driver, body.expected_version)
            driver.version += 1
            driver.facts = {
                **driver.facts,
                "routing_origin": body.origin.model_dump(mode="json"),
                "routing_origin_observed_at": now.isoformat(),
            }
            return DriverOriginRead(
                driver_id=driver.id, version=driver.version, origin=body.origin, observed_at=now
            ).model_dump(mode="json")

        return command(
            self.sessions,
            actor,
            "POST /api/v1/driver-origin",
            key,
            body.model_dump(mode="json"),
            self.clock,
            apply,
        )

    def driver_origin(self, actor):
        require_role(actor, "driver")
        with self.sessions() as session:
            driver = session.scalar(
                select(Driver).where(
                    Driver.user_id == actor.user_id, Driver.organization_id == actor.organization_id
                )
            )
            if driver is None:
                raise AppError("driver_unavailable", "Driver profile is not provisioned.", 404)
            data = driver.facts
            return DriverOriginRead(
                driver_id=driver.id,
                version=driver.version,
                origin=data.get("routing_origin"),
                observed_at=(
                    datetime.fromisoformat(data["routing_origin_observed_at"])
                    if "routing_origin_observed_at" in data
                    else None
                ),
            )

    def update_profile(self, actor, body, key, correlation_id):
        require_role(actor, "recipient")

        def apply(session, now):
            row, original, capacities = current_profile(session, actor.organization_id, lock=True)
            require_version(row, body.expected_version)
            if (
                body.profile.organization_id != actor.organization_id
                or body.profile.version != row.version
            ):
                raise AppError("invalid_profile", "Refresh your organization profile.", 409)
            if body.profile.location != original.location:
                raise AppError(
                    "location_review_required",
                    "Ask your coordinator to verify location changes.",
                    422,
                )
            if body.profile.receiving_window.end <= now:
                raise AppError("receiving_window_passed", "Choose a future receiving window.", 422)
            from foodbridge.agents.intake.policy import ALLERGENS, normalize

            if not {normalize(value) for value in body.profile.rejected_allergens} <= ALLERGENS:
                raise AppError(
                    "allergens_need_review", "Use standard allergen names, such as soy.", 422
                )
            if body.expected_capacity_versions != {s: c.version for s, c in capacities.items()}:
                raise AppError(
                    "capacity_changed", "Reservations changed. Refresh capacity before saving.", 409
                )
            if set(body.reported_free_kg_by_storage) != set(body.profile.accepted_storage):
                raise AppError(
                    "invalid_capacity", "Provide capacity for every accepted storage type.", 422
                )
            for storage, value in body.reported_free_kg_by_storage.items():
                amount = Decimal(str(value))
                if amount != amount.quantize(Decimal("0.001")) or amount > Decimal("999999999.999"):
                    raise AppError(
                        "invalid_capacity", "Use up to three decimals for capacity.", 422
                    )
                cap = capacities.get(storage)
                if cap and amount < cap.committed_inbound_kg:
                    raise AppError(
                        "capacity_committed",
                        "Free storage cannot be below committed inbound food.",
                        409,
                    )
            for storage, cap in capacities.items():
                if storage not in body.reported_free_kg_by_storage:
                    if cap.committed_inbound_kg:
                        raise AppError(
                            "capacity_committed", "A storage type has committed inbound food.", 409
                        )
                    session.delete(cap)
            for storage, value in body.reported_free_kg_by_storage.items():
                cap = capacities.get(storage)
                if cap is None:
                    session.add(
                        Capacity(
                            organization_id=actor.organization_id,
                            storage=storage,
                            reported_free_kg=Decimal(str(value)),
                            committed_inbound_kg=0,
                            version=1,
                        )
                    )
                else:
                    cap.reported_free_kg = Decimal(str(value))
                    cap.version += 1
            row.profile = body.profile.model_dump(mode="json")
            row.version += 1
            session.flush()
            event = enqueue_event(
                session,
                actor.organization_id,
                row.version,
                "recipient.updated.v1",
                now,
                correlation_id,
                {"organization_id": str(actor.organization_id)},
            )
            event.audience = [
                {"organization_id": str(actor.organization_id), "role": "recipient"},
                {"organization_id": str(actor.organization_id), "role": "operator"},
            ]
            return self.profile_view(session, actor.organization_id).model_dump(mode="json")

        return command(
            self.sessions,
            actor,
            "POST /api/v1/receiving-profile",
            key,
            body.model_dump(mode="json"),
            self.clock,
            apply,
        )

    def offer_view(self, session, row):
        return OfferRead(
            recommendation=row.recommendation,
            status=row.status,
            version=row.version,
            donation=snapshot(session.get(Donation, row.donation_id), self.clock()),
        )

    def pickup_view(self, session, row):
        donation = session.get(Donation, row.donation_id)
        result = ReservationService.pickup_view(row, donation, self.clock())
        reservation = session.get(Reservation, row.reservation_id)
        _, profile, _ = current_profile(session, reservation.recipient_organization_id)
        org = session.get(Organization, reservation.recipient_organization_id)
        result["destination"], result["recipient_name"] = (
            profile.location.model_dump(mode="json"),
            org.name,
        )
        return result
