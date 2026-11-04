"""Event consumption and fenced workflow execution."""

from foodbridge.agents.celery_app import celery_app


@celery_app.task(name="foodbridge.orchestrator.probe")
def probe() -> dict[str, str]:
    """Diagnostic only: verifies registration, not business functionality."""
    return {"worker": "orchestrator", "status": "registered"}


def service():
    from foodbridge.agents.orchestrator.service import WorkflowService
    from foodbridge.settings import Settings

    settings = Settings()
    return WorkflowService(
        settings.database_url, allow_synthetic=settings.enable_local_workflow_demo
    ), settings


@celery_app.task(name="foodbridge.orchestrator.consume", acks_late=True)
def consume(event_id: str):
    from uuid import UUID

    coordinator, _ = service()
    coordinator.consume(UUID(event_id))


@celery_app.task(name="foodbridge.orchestrator.plan_step", acks_late=True)
def plan_step(step_id: str):
    from uuid import UUID

    from foodbridge.agents.orchestrator.agent import OrchestratorAgent
    from foodbridge.settings import Settings

    OrchestratorAgent(Settings()).plan_step(UUID(step_id))


@celery_app.task(name="foodbridge.orchestrator.run_step", acks_late=True)
def run_step(step_id: str):
    from uuid import UUID

    from foodbridge.integrations.workflow import matching_gateway

    coordinator, settings = service()
    coordinator.run_step(UUID(step_id), matching_gateway(settings))
