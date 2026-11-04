"""Asynchronous notification delivery around synchronous reservation transactions."""

from foodbridge.agents.celery_app import celery_app


@celery_app.task(name="foodbridge.reservation.probe")
def probe() -> dict[str, str]:
    """Diagnostic only: verifies registration, not business functionality."""
    return {"worker": "reservation", "status": "registered"}


@celery_app.task(name="foodbridge.reservation.deliver_notifications", acks_late=True)
def deliver_notifications():
    from foodbridge.agents.reservation.notifications import deliver_pending, notification_provider
    from foodbridge.settings import Settings

    settings = Settings()
    return deliver_pending(settings.database_url, notification_provider(settings))


@celery_app.task(name="foodbridge.reservation.assign", acks_late=True)
def assign(step_id: str):
    from uuid import UUID

    from foodbridge.agents.orchestrator.service import WorkflowService
    from foodbridge.integrations.workflow import matching_gateway
    from foodbridge.settings import Settings

    settings = Settings()
    WorkflowService(
        settings.database_url, allow_synthetic=settings.enable_local_workflow_demo
    ).run_step(UUID(step_id), matching_gateway(settings))
