"""Commit-ordered, membership-scoped SSE replay; broker and stream markers are independent."""

from datetime import timedelta

from sqlalchemy import func, select, text

from foodbridge.agents.intake.service import utcnow
from foodbridge.db.models import OutboxEvent
from foodbridge.db.session import session_factory
from foodbridge.db.workflow_models import StreamEvent, StreamState
from foodbridge.domain.errors import AppError

STREAM_LOCK = 7348091


def publish_stream(database_url, clock=utcnow, limit=100):
    with session_factory(database_url).begin() as session:
        if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": STREAM_LOCK}):
            return 0
        now = clock()
        rows = list(
            session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.stream_published_at.is_(None), OutboxEvent.audience.is_not(None))
                .order_by(OutboxEvent.envelope["occurred_at"].as_string(), OutboxEvent.event_id)
                .limit(limit)
            )
        )
        for row in rows:
            session.add(
                StreamEvent(
                    event_id=row.event_id,
                    envelope=row.envelope,
                    audience=row.audience,
                    published_at=now,
                )
            )
            row.stream_published_at = now
        return len(rows)


class StreamService:
    def __init__(self, database_url, clock=utcnow):
        self.sessions, self.clock = session_factory(database_url), clock

    def cursor(self, value):
        with self.sessions() as session:
            latest = session.scalar(select(func.max(StreamEvent.sequence))) or 0
            state = session.get(StreamState, 1)
            floor = state.expired_through if state else 0
            latest = max(latest, floor)
            if value is None:
                return latest
            try:
                cursor = int(value)
                if cursor < 0 or cursor > latest:
                    raise ValueError
            except ValueError as exc:
                raise AppError("invalid_stream_cursor", "Invalid stream cursor.", 400) from exc
            if cursor < floor:
                raise AppError("stream_cursor_expired", "Refresh snapshots and reconnect.", 409)
            return cursor

    def read(self, actor, after, limit=100):
        target = (
            {"user_id": str(actor.user_id), "role": "driver"}
            if actor.role == "driver"
            else {"organization_id": str(actor.organization_id), "role": actor.role}
        )
        with self.sessions() as session:
            rows = list(
                session.scalars(
                    select(StreamEvent)
                    .where(StreamEvent.sequence > after, StreamEvent.audience.contains([target]))
                    .order_by(StreamEvent.sequence)
                    .limit(limit)
                )
            )
            return [{"sequence": row.sequence, "event": row.envelope} for row in rows]

    def prune(self):
        """Explicit maintenance command; default retention is seven days."""
        with self.sessions.begin() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": STREAM_LOCK})
            cutoff = self.clock() - timedelta(days=7)
            rows = list(
                session.scalars(
                    select(StreamEvent)
                    .where(StreamEvent.published_at < cutoff)
                    .order_by(StreamEvent.sequence)
                )
            )
            if not rows:
                return 0
            state = session.get(StreamState, 1)
            if state is None:
                state = StreamState(id=1, expired_through=0)
                session.add(state)
            state.expired_through = max(state.expired_through, rows[-1].sequence)
            for row in rows:
                session.delete(row)
            return len(rows)
