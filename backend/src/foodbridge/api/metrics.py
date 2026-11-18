"""Protected deployment metrics; bounded labels and no user data or credentials."""

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from foodbridge.db.models import OutboxEvent
from foodbridge.db.session import session_factory
from foodbridge.db.workflow_models import Notification, WorkflowStep
from foodbridge.domain.errors import AppError

router = APIRouter()


@router.get("/internal/metrics", include_in_schema=False)
def metrics(request: Request):
    settings = request.app.state.settings
    expected = settings.metrics_token.get_secret_value() if settings.metrics_token else ""
    if not expected or not secrets.compare_digest(
        request.headers.get("authorization", ""), f"Bearer {expected}"
    ):
        raise AppError("not_found", "Not found.", 404)
    registry = CollectorRegistry()
    available = Gauge(
        "foodbridge_dependencies_available", "DB/Redis collection succeeded", registry=registry
    )
    pending = Gauge("foodbridge_outbox_pending", "Unpublished outbox events", registry=registry)
    age = Gauge(
        "foodbridge_workflow_overdue_seconds",
        "Seconds beyond oldest due pending step",
        registry=registry,
    )
    steps = Gauge("foodbridge_steps", "Persisted workflow steps", ["status"], registry=registry)
    notifications = Gauge(
        "foodbridge_notifications",
        "Persisted notification delivery outcomes",
        ["status"],
        registry=registry,
    )
    queues = Gauge(
        "foodbridge_queue_depth",
        "Queued messages at default priority",
        ["queue"],
        registry=registry,
    )
    try:
        with session_factory(settings.database_url)() as session:
            pending.set(
                session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.published_at.is_(None))
                )
            )
            due = session.scalar(
                select(func.min(WorkflowStep.next_attempt_at)).where(
                    WorkflowStep.status == "pending"
                )
            )
            age.set(max(0, (datetime.now(UTC) - due).total_seconds()) if due else 0)
            for status in ("pending", "running", "completed", "stale", "failed"):
                steps.labels(status).set(
                    session.scalar(
                        select(func.count())
                        .select_from(WorkflowStep)
                        .where(WorkflowStep.status == status)
                    )
                )
            for status in ("pending", "sending", "sent", "failed"):
                notifications.labels(status).set(
                    session.scalar(
                        select(func.count())
                        .select_from(Notification)
                        .where(Notification.status == status)
                    )
                )
        with Redis.from_url(settings.redis_url, socket_timeout=3) as redis:
            for queue in ("intake", "matching", "orchestrator", "reservation"):
                queues.labels(queue).set(redis.llen(queue))
        available.set(1)
    except (OperationalError, RedisError):
        available.set(0)
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
