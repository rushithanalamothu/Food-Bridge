"""Committed recipient/driver commands with version, deadline and capacity boundaries."""

from uuid import uuid4

from sqlalchemy import select

from foodbridge.agents.intake.config import load_policy
from foodbridge.agents.intake.policy import evaluate
from foodbridge.agents.intake.service import utcnow
from foodbridge.db.models import IntakeEvaluation, Organization
from foodbridge.db.session import session_factory
from foodbridge.db.workflow import (
    amount,
    audience,
    command,
    conflict,
    current_profile,
    deadline,
    locked_donation,
    release_all,
    require_role,
    require_version,
    snapshot,
    transition,
)
from foodbridge.db.workflow_models import Assignment, Driver, Impact, MatchOffer, Reservation
from foodbridge.domain.errors import AppError
from foodbridge.domain.intake import DriverFacts, EligibilityBatch, EligibilityCandidate
from foodbridge.domain.workflow import PickupRead, ReservationRead


class ReservationService:
    def __init__(self, database_url, clock=utcnow, *, allow_synthetic=False):
        self.sessions = session_factory(database_url)
        self.clock, self.allow_synthetic = clock, allow_synthetic
        self.policy = load_policy()

    @staticmethod
    def reservation_view(row, donation):
        return ReservationRead(
            id=row.id,
            donation_id=row.donation_id,
            match_id=row.match_id,
            recipient_organization_id=row.recipient_organization_id,
            quantity_kg=float(row.quantity_kg),
            storage=row.storage,
            status=row.status,
            version=row.version,
            donation_version=donation.version,
            created_at=row.created_at,
        ).model_dump(mode="json")

    @staticmethod
    def pickup_view(row, donation, now):
        return PickupRead(
            id=row.id,
            donation_id=row.donation_id,
            reservation_id=row.reservation_id,
            driver_id=row.driver_id,
            status=row.status,
            version=row.version,
            start=row.start,
            end=row.end,
            donation=snapshot(donation, now),
        ).model_dump(mode="json")

    def eligible(self, session, donation, offer, now, *, lock=False, driver_facts=None):
        state, profile, capacities = current_profile(
            session, offer.recipient_organization_id, lock=lock
        )
        saved = EligibilityCandidate.model_validate(offer.candidate)
        if state.version != saved.recipient.version:
            conflict("recipient_profile_changed")
        org = session.get(Organization, offer.recipient_organization_id)
        driver = session.get(Driver, saved.driver.id) if saved.driver else None
        if driver_facts is None:
            if driver is None or driver.version != offer.driver_version:
                conflict("driver_changed")
            facts = DriverFacts.model_validate(driver.facts)
            # Travel to this donor is specific to the route snapshot, not generic driver settings.
            driver_facts = facts.model_copy(
                update={"to_pickup_time_s": saved.driver.to_pickup_time_s}
            )
        evaluation = session.get(IntakeEvaluation, offer.evaluation_id)
        synthetic = bool(evaluation.batch.get("synthetic"))
        if synthetic and not self.allow_synthetic:
            conflict("synthetic_evaluation_disabled")
        candidate = saved.model_copy(
            update={
                "recipient": profile,
                "active_and_verified": bool(state.verified and org and org.active),
                "driver": driver_facts,
            }
        )
        result = evaluate(
            snapshot(donation, now),
            EligibilityBatch(
                donation_id=donation.id,
                expected_donation_version=donation.version,
                candidates=[candidate],
                synthetic=synthetic,
            ),
            now,
            self.policy,
        )
        decision = result.decisions[0]
        if not decision.eligible:
            conflict("eligibility_changed")
        return capacities, candidate, decision

    def reserve(self, actor, body, key, correlation_id):
        require_role(actor, "recipient")

        def apply(session, now):
            initial = session.get(MatchOffer, body.match_id)
            if initial is None or initial.recipient_organization_id != actor.organization_id:
                raise AppError("not_found", "Not found.", 404)
            donation = locked_donation(session, initial.donation_id)
            offer = session.get(MatchOffer, body.match_id, populate_existing=True)
            require_version(donation, body.expected_donation_version)
            deadline(donation, now)
            if (
                donation.status != "offered"
                or offer.status != "offered"
                or offer.expires_at <= now
                or offer.matching_round != donation.matching_round
            ):
                conflict("offer_expired")
            capacities, _, _ = self.eligible(session, donation, offer, now, lock=True)
            storage = donation.confirmed_data["storage"]
            capacity = capacities[storage]
            if capacity.reported_free_kg - capacity.committed_inbound_kg < donation.quantity_kg:
                conflict("capacity_conflict")
            capacity.committed_inbound_kg += donation.quantity_kg
            capacity.version += 1
            row = Reservation(
                id=uuid4(),
                donation_id=donation.id,
                match_id=offer.id,
                recipient_organization_id=offer.recipient_organization_id,
                quantity_kg=donation.quantity_kg,
                storage=storage,
                created_at=now,
            )
            session.add(row)
            offer.status, offer.version = "accepted", offer.version + 1
            transition(
                session,
                donation,
                "reserved",
                "recipient_accepted",
                now,
                correlation_id,
                actor.user_id,
            )
            return self.reservation_view(row, donation)

        return command(
            self.sessions,
            actor,
            "POST /api/v1/reservations",
            key,
            body.model_dump(mode="json"),
            self.clock,
            apply,
        )

    def decline(self, actor, match_id, body, key, correlation_id):
        require_role(actor, "recipient")

        def apply(session, now):
            offer = session.get(MatchOffer, match_id)
            if offer is None or offer.recipient_organization_id != actor.organization_id:
                raise AppError("not_found", "Not found.", 404)
            donation = locked_donation(session, offer.donation_id)
            session.refresh(offer)
            require_version(offer, body.expected_version)
            deadline(donation, now)
            if donation.status != "offered" or offer.status != "offered" or offer.expires_at <= now:
                conflict("offer_expired")
            offer.status, offer.version = "declined", offer.version + 1
            donation.matching_round += 1
            transition(
                session,
                donation,
                "matching",
                "recipient_declined",
                now,
                correlation_id,
                actor.user_id,
            )
            return snapshot(donation, now).model_dump(mode="json")

        return command(
            self.sessions,
            actor,
            f"POST /api/v1/matches/{match_id}/decline",
            key,
            body.model_dump(mode="json"),
            self.clock,
            apply,
        )

    def release(self, actor, reservation_id, body, key, correlation_id):
        require_role(actor, "recipient", "operator")

        def apply(session, now):
            row = session.get(Reservation, reservation_id)
            if row is None or row.recipient_organization_id != actor.organization_id:
                raise AppError("not_found", "Not found.", 404)
            donation = locked_donation(session, row.donation_id)
            session.refresh(row)
            require_version(row, body.expected_version)
            if row.status != "active" or donation.status not in {"reserved", "pickup_assigned"}:
                conflict("release_not_allowed")
            release_all(session, donation)
            # Release of an assignment returns the lifecycle to reserved first.
            if donation.status == "pickup_assigned":
                transition(
                    session,
                    donation,
                    "reserved",
                    "assignment_released",
                    now,
                    correlation_id,
                    actor.user_id,
                )
            donation.matching_round += 1
            target = (
                "expired" if now >= min(donation.pickup_end, donation.safe_use_by) else "matching"
            )
            transition(
                session, donation, target, "recipient_released", now, correlation_id, actor.user_id
            )
            return self.reservation_view(row, donation)

        return command(
            self.sessions,
            actor,
            f"POST /api/v1/reservations/{reservation_id}/release",
            key,
            body.model_dump(mode="json"),
            self.clock,
            apply,
        )

    def cancel(self, actor, donation_id, body, key, correlation_id):
        require_role(actor, "donor", "operator")

        def apply(session, now):
            donation = locked_donation(session, donation_id)
            if donation.donor_organization_id != actor.organization_id:
                raise AppError("not_found", "Not found.", 404)
            require_version(donation, body.expected_donation_version)
            if donation.status not in {
                "submitted",
                "needs_review",
                "matching",
                "offered",
                "reserved",
                "pickup_assigned",
            }:
                conflict("cancellation_not_allowed")
            release_all(session, donation)
            transition(
                session,
                donation,
                "cancelled",
                "donor_cancelled",
                now,
                correlation_id,
                actor.user_id,
            )
            return snapshot(donation, now).model_dump(mode="json")

        return command(
            self.sessions,
            actor,
            f"POST /api/v1/donations/{donation_id}/cancel",
            key,
            body.model_dump(mode="json"),
            self.clock,
            apply,
        )

    def assign(self, session, donation, offer, candidate, now, correlation_id):
        """Trusted candidate facts must come from routing, never the browser."""
        reservation = session.scalar(
            select(Reservation).where(
                Reservation.donation_id == donation.id, Reservation.status == "active"
            )
        )
        if reservation is None or donation.status != "reserved":
            conflict("reservation_not_active")
        driver = session.get(Driver, candidate.driver.id, with_for_update=True)
        if driver is None:
            conflict("driver_unavailable")
        facts = DriverFacts.model_validate(driver.facts)
        candidate.driver = facts.model_copy(
            update={"to_pickup_time_s": candidate.driver.to_pickup_time_s}
        )
        # The reservation's own inbound allocation is available to this feasibility check.
        _, profile, _ = current_profile(session, reservation.recipient_organization_id)
        available = dict(profile.available_capacity_kg_by_storage)
        available[reservation.storage] += float(reservation.quantity_kg)
        candidate.recipient = profile.model_copy(
            update={"available_capacity_kg_by_storage": available}
        )
        evaluation = session.get(IntakeEvaluation, offer.evaluation_id)
        synthetic = bool(evaluation.batch.get("synthetic"))
        if synthetic and not self.allow_synthetic:
            conflict("synthetic_evaluation_disabled")
        org = session.get(Organization, reservation.recipient_organization_id)
        state, _, _ = current_profile(session, reservation.recipient_organization_id)
        candidate.active_and_verified = bool(org and org.active and state.verified)
        decision = evaluate(
            snapshot(donation, now),
            EligibilityBatch(
                donation_id=donation.id,
                expected_donation_version=donation.version,
                candidates=[candidate],
                synthetic=synthetic,
            ),
            now,
            self.policy,
        ).decisions[0]
        if not decision.eligible:
            conflict("driver_infeasible")
        start, end = now, decision.arrival_at
        overlap = session.scalar(
            select(Assignment.id).where(
                Assignment.driver_id == driver.id,
                Assignment.status.in_(["assigned", "accepted", "collected"]),
                Assignment.start < end,
                Assignment.end > start,
            )
        )
        if overlap:
            conflict("driver_busy")
        row = Assignment(
            id=uuid4(),
            donation_id=donation.id,
            reservation_id=reservation.id,
            driver_id=driver.id,
            candidate=candidate.model_dump(mode="json"),
            start=start,
            end=end,
            created_at=now,
        )
        session.add(row)
        transition(session, donation, "pickup_assigned", "driver_assigned", now, correlation_id)
        return row

    def pickup_command(self, actor, identifier, verb, body, key, correlation_id):
        require_role(actor, "driver")

        def apply(session, now):
            row = session.get(Assignment, identifier)
            driver = session.get(Driver, row.driver_id) if row else None
            if (
                row is None
                or driver.user_id != actor.user_id
                or driver.organization_id != actor.organization_id
            ):
                raise AppError("not_found", "Not found.", 404)
            donation = locked_donation(session, row.donation_id)
            session.refresh(row)
            driver = session.get(
                Driver, row.driver_id, with_for_update=True, populate_existing=True
            )
            require_version(row, body.expected_version)
            if verb in {"accept", "decline", "confirm-pickup"}:
                deadline(donation, now)
                if row.end <= now:
                    conflict("assignment_expired")
            if verb == "accept":
                if row.status != "assigned" or donation.status != "pickup_assigned":
                    conflict("assignment_not_pending")
                row.status = "accepted"
            elif verb == "decline":
                if (
                    row.status not in {"assigned", "accepted"}
                    or donation.status != "pickup_assigned"
                ):
                    conflict("assignment_not_pending")
                row.status = "declined"
                transition(
                    session,
                    donation,
                    "reserved",
                    "driver_declined",
                    now,
                    correlation_id,
                    actor.user_id,
                )
            elif verb == "confirm-pickup":
                if row.status != "accepted" or donation.status != "pickup_assigned":
                    conflict("pickup_not_allowed")
                if now < donation.pickup_start:
                    conflict("pickup_window_not_open")
                if amount(body.observed_quantity_kg) != donation.quantity_kg:
                    conflict("quantity_adjustment_required")
                offer = session.get(
                    MatchOffer, session.get(Reservation, row.reservation_id).match_id
                )
                # Include this reservation's own inbound commitment during revalidation.
                _, profile, _ = current_profile(session, offer.recipient_organization_id)
                receiving = session.get(Reservation, row.reservation_id)
                capacities = dict(profile.available_capacity_kg_by_storage)
                capacities[receiving.storage] += float(receiving.quantity_kg)
                profile = profile.model_copy(
                    update={"available_capacity_kg_by_storage": capacities}
                )
                candidate = EligibilityCandidate.model_validate(row.candidate)
                facts = DriverFacts.model_validate(driver.facts)
                candidate.recipient = profile
                candidate.driver = facts.model_copy(update={"to_pickup_time_s": 0})
                state, _, _ = current_profile(session, offer.recipient_organization_id)
                org = session.get(Organization, offer.recipient_organization_id)
                candidate.active_and_verified = bool(state.verified and org and org.active)
                evaluation = session.get(IntakeEvaluation, offer.evaluation_id)
                synthetic = bool(evaluation.batch.get("synthetic"))
                if synthetic and not self.allow_synthetic:
                    conflict("synthetic_evaluation_disabled")
                decision = evaluate(
                    snapshot(donation, now),
                    EligibilityBatch(
                        donation_id=donation.id,
                        expected_donation_version=donation.version,
                        candidates=[candidate],
                        synthetic=synthetic,
                    ),
                    now,
                    self.policy,
                ).decisions[0]
                if not decision.eligible or decision.pickup_at > now:
                    conflict("pickup_infeasible")
                row.status = "collected"
                transition(
                    session,
                    donation,
                    "picked_up",
                    "driver_collected",
                    now,
                    correlation_id,
                    actor.user_id,
                )
            elif verb == "confirm-delivery":
                if row.status != "collected" or donation.status != "picked_up":
                    conflict("delivery_not_allowed")
                if now >= donation.safe_use_by:
                    conflict("safe_use_deadline_passed")
                reservation = session.get(Reservation, row.reservation_id)
                _, profile, capacities = current_profile(
                    session, reservation.recipient_organization_id, lock=True
                )
                if not profile.receiving_window.start <= now <= profile.receiving_window.end:
                    conflict("recipient_closed")
                cap = capacities[reservation.storage]
                cap.committed_inbound_kg -= reservation.quantity_kg
                cap.reported_free_kg -= reservation.quantity_kg
                cap.version += 1
                reservation.status, reservation.version = "completed", reservation.version + 1
                row.status = "delivered"
                session.add(
                    Impact(
                        donation_id=donation.id,
                        recipient_organization_id=reservation.recipient_organization_id,
                        quantity_kg=reservation.quantity_kg,
                        delivered_at=now,
                    )
                )
                transition(
                    session,
                    donation,
                    "delivered",
                    "driver_delivered",
                    now,
                    correlation_id,
                    actor.user_id,
                )
            else:
                raise AppError("unknown_command", "Unknown pickup command.")
            row.version += 1
            if verb == "accept":
                # Assignment acceptance is a versioned aggregate change with its own event.
                from foodbridge.db.transactions import enqueue_event as _event

                accepted_event = _event(
                    session,
                    row.id,
                    row.version,
                    "pickup.accepted.v1",
                    now,
                    correlation_id,
                    {
                        "donation_id": str(donation.id),
                        "status": "accepted",
                        "donation_version": donation.version,
                    },
                )
                accepted_event.audience = audience(session, donation)
            session.flush()
            return self.pickup_view(row, donation, now)

        return command(
            self.sessions,
            actor,
            f"POST /api/v1/pickups/{identifier}/{verb}",
            key,
            body.model_dump(mode="json"),
            self.clock,
            apply,
        )
