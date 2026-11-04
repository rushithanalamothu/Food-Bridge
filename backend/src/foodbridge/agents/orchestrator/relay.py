"""General outbox broker relay; the existing intake relay retains its own request events."""

from datetime import timedelta

from kombu.exceptions import OperationalError as BrokerError
from sqlalchemy import exists, or_, select

from foodbridge.agents.intake.relay import EVENT_TYPE as INTAKE_REQUEST
from foodbridge.agents.intake.service import utcnow
from foodbridge.db.models import OutboxEvent
from foodbridge.db.session import session_factory
from foodbridge.db.workflow_models import ConsumerReceipt


def dispatch_pending(settings, publish=None, clock=utcnow, limit=50):
    if publish is None:
        from foodbridge.agents.celery_app import celery_app

        def publish(identifier):
            celery_app.send_task("foodbridge.orchestrator.consume", args=[identifier], retry=False)

    sessions = session_factory(settings.database_url)
    dispatched = 0
    for _ in range(limit):
        now = clock()
        with sessions.begin() as session:
            row = session.scalar(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type != INTAKE_REQUEST,
                    or_(
                        OutboxEvent.published_at.is_(None),
                        (OutboxEvent.published_at <= now - timedelta(seconds=75))
                        & ~exists().where(
                            ConsumerReceipt.consumer == "orchestrator",
                            ConsumerReceipt.event_id == OutboxEvent.event_id,
                        ),
                    ),
                    or_(OutboxEvent.lease_until.is_(None), OutboxEvent.lease_until <= now),
                )
                .order_by(OutboxEvent.envelope["occurred_at"].as_string(), OutboxEvent.event_id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                break
            identifier, lease = row.event_id, now + timedelta(seconds=30)
            row.lease_until, row.attempts = lease, row.attempts + 1
        try:
            publish(str(identifier))
        except (BrokerError, OSError):
            break
        with sessions.begin() as session:
            row = session.get(OutboxEvent, identifier, with_for_update=True)
            if row.lease_until == lease:
                row.published_at, row.lease_until = clock(), None
        dispatched += 1
    return dispatched
