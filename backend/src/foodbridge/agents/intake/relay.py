"""Intake-only outbox relay. Other event types remain available for the orchestrator owner."""

import time
from datetime import timedelta
from uuid import UUID

from kombu.exceptions import OperationalError
from sqlalchemy import or_, select

from foodbridge.agents.intake.service import utcnow
from foodbridge.db.models import OutboxEvent
from foodbridge.db.session import session_factory
from foodbridge.observability import publication_retries, record
from foodbridge.settings import Settings

EVENT_TYPE = "intake.evaluation_requested.v1"


def dispatch_pending(
    settings: Settings, publish=None, limit: int = 20, evaluation_id: UUID | None = None
) -> int:
    if publish is None:
        from foodbridge.agents.celery_app import celery_app

        def publish(identifier):
            celery_app.send_task("foodbridge.intake.evaluate", args=[identifier], retry=False)

    sessions = session_factory(settings.database_url)
    dispatched = 0
    for _ in range(limit):
        now = utcnow()
        with sessions.begin() as session:
            row = session.scalar(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == EVENT_TYPE,
                    True if evaluation_id is None else OutboxEvent.aggregate_id == evaluation_id,
                    OutboxEvent.published_at.is_(None),
                    or_(OutboxEvent.lease_until.is_(None), OutboxEvent.lease_until < now),
                )
                .order_by(OutboxEvent.event_id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                break
            correlation_id = UUID(row.envelope["correlation_id"])
            donation_id = row.envelope.get("payload", {}).get("donation_id")
            donation_id = UUID(donation_id) if donation_id else None
            attempts = row.attempts + 1
            event_id, selected_id = row.event_id, row.aggregate_id
            lease = now + timedelta(seconds=30)
            row.lease_until, row.attempts = lease, row.attempts + 1
        started = time.perf_counter()
        try:
            publish(str(selected_id))
        except (OperationalError, OSError):
            publication_retries.inc()
            record(
                "event.publish_failed",
                request_id=correlation_id,
                donation_id=donation_id,
                event_id=event_id,
                evaluation_id=selected_id,
                outcome="broker_unavailable",
                duration_ms=(time.perf_counter() - started) * 1000,
                attempts=attempts,
            )
            # Persisted work remains pending; a later relay retries after the lease.
            break
        with sessions.begin() as session:
            row = session.get(OutboxEvent, event_id, with_for_update=True)
            if row.lease_until == lease:
                row.published_at, row.lease_until = utcnow(), None
        dispatched += 1
    return dispatched


def main() -> None:
    settings = Settings()
    while True:
        dispatch_pending(settings)
        time.sleep(3)


if __name__ == "__main__":
    main()
