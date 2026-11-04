"""Shared transaction primitives; no provider/network operations while locks are held."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from foodbridge.agents.intake.service import donation_view
from foodbridge.db.models import Donation, StatusHistory
from foodbridge.db.transactions import enqueue_event as _event
from foodbridge.db.transactions import idempotency as _idempotency
from foodbridge.db.transactions import remember_response as _remember
from foodbridge.db.workflow_models import (
    Assignment,
    Capacity,
    Driver,
    MatchOffer,
    RecipientState,
    Reservation,
)
from foodbridge.domain.contracts import RecipientProfile
from foodbridge.domain.errors import AppError
from foodbridge.domain.states import DonationStatus, assert_transition


def conflict(code="stale_version"):
    raise AppError(
        code, "State changed or the action is no longer feasible. Refresh and retry.", 409
    )


def require_role(actor, *roles):
    if actor.role not in roles:
        raise AppError("role_required", "This role cannot perform that action.", 403)


def locked_donation(session, identifier):
    row = session.get(Donation, identifier, with_for_update=True)
    if row is None:
        raise AppError("not_found", "Not found.", 404)
    return row


def require_version(row, expected):
    if row.version != expected:
        conflict()


def deadline(row, now):
    if now >= min(row.pickup_end, row.safe_use_by):
        conflict("donation_expired")


def current_profile(session, org_id, *, lock=False):
    row = session.get(RecipientState, org_id, with_for_update=lock)
    if row is None:
        conflict("recipient_unavailable")
    rows = list(
        session.scalars(
            select(Capacity)
            .where(Capacity.organization_id == org_id)
            .order_by(Capacity.storage)
            .with_for_update()
            if lock
            else select(Capacity).where(Capacity.organization_id == org_id)
        )
    )
    profile = RecipientProfile.model_validate(
        {
            **row.profile,
            "organization_id": str(org_id),
            "version": row.version,
            "available_capacity_kg_by_storage": {
                c.storage: float(c.reported_free_kg - c.committed_inbound_kg) for c in rows
            },
        }
    )
    return row, profile, {c.storage: c for c in rows}


def audience(session, donation):
    targets = [
        {"organization_id": str(donation.donor_organization_id), "role": "donor"},
        {"organization_id": str(donation.donor_organization_id), "role": "operator"},
    ]
    recipients = set(
        session.scalars(
            select(MatchOffer.recipient_organization_id).where(
                MatchOffer.donation_id == donation.id
            )
        )
    )
    for org in recipients:
        targets += [
            {"organization_id": str(org), "role": "recipient"},
            {"organization_id": str(org), "role": "operator"},
        ]
    drivers = session.execute(
        select(Driver.user_id, Driver.organization_id)
        .join(Assignment, Assignment.driver_id == Driver.id)
        .where(Assignment.donation_id == donation.id)
    ).all()
    for user, org in drivers:
        targets += [
            {"user_id": str(user), "role": "driver"},
            {"organization_id": str(org), "role": "operator"},
        ]
    return targets


def transition(session, donation, target, reason, now, correlation_id, actor_id=None):
    assert_transition(DonationStatus(donation.status), DonationStatus(target))
    previous = donation.status
    donation.status, donation.version = target, donation.version + 1
    session.add(
        StatusHistory(
            id=uuid4(),
            donation_id=donation.id,
            aggregate_version=donation.version,
            previous_status=previous,
            next_status=target,
            actor_id=actor_id,
            reason=reason,
            correlation_id=correlation_id,
            occurred_at=now,
        )
    )
    session.flush()
    kind = {
        "offered": "match.offered.v1",
        "reserved": "reservation.created.v1",
        "pickup_assigned": "pickup.assigned.v1",
        "picked_up": "pickup.collected.v1",
        "delivered": "pickup.delivered.v1",
        "expired": "donation.expired.v1",
        "cancelled": "donation.cancelled.v1",
        "failed": "workflow.failed.v1",
    }.get(target, "donation.updated.v1")
    _event(
        session,
        donation.id,
        donation.version,
        kind,
        now,
        correlation_id,
        {"status": target, "reason": reason, "matching_round": donation.matching_round},
    )
    session.flush()
    from foodbridge.db.models import OutboxEvent

    event = session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.aggregate_id == donation.id,
            OutboxEvent.aggregate_version == donation.version,
            OutboxEvent.event_type == kind,
        )
    )
    event.audience = audience(session, donation)
    return event


def release_all(session, donation, *, failure=False):
    """Called with donation locked; inbound allocation is returned at most once."""
    reservation = session.scalar(
        select(Reservation).where(
            Reservation.donation_id == donation.id, Reservation.status == "active"
        )
    )
    if reservation:
        _, _, capacities = current_profile(
            session, reservation.recipient_organization_id, lock=True
        )
        cap = capacities[reservation.storage]
        cap.committed_inbound_kg -= reservation.quantity_kg
        cap.version += 1
        reservation.status = "failed" if failure else "released"
        reservation.version += 1
    for assignment in session.scalars(
        select(Assignment).where(
            Assignment.donation_id == donation.id,
            Assignment.status.in_(["assigned", "accepted", "collected"]),
        )
    ):
        assignment.status = "failed" if failure else "released"
        assignment.version += 1
    for offer in session.scalars(
        select(MatchOffer).where(
            MatchOffer.donation_id == donation.id, MatchOffer.status == "offered"
        )
    ):
        offer.status = "expired" if failure else "superseded"
        offer.version += 1


def command(sessions, actor, action, key, body, clock, callback):
    """Receipt and response commit with effects. Retry only rolled-back database transactions."""
    for attempt in range(3):
        try:
            with sessions.begin() as session:
                # Serialize the same actor/route/key before acquiring business rows.
                saved, digest = _idempotency(session, actor.user_id, action, key, body)
                if saved:
                    return saved.response
                result = callback(session, clock())
                _remember(session, actor.user_id, action, key, digest, result, clock())
                return result
        except OperationalError as exc:
            if getattr(exc.orig, "sqlstate", None) not in {"40001", "40P01"} or attempt == 2:
                raise


def snapshot(row, now):
    return donation_view(row, now).donation


def amount(value):
    result = Decimal(str(value))
    if result <= 0 or result != result.quantize(Decimal("0.001")):
        raise AppError(
            "invalid_quantity", "Quantity needs kilogram precision of at most 0.001.", 422
        )
    return result
