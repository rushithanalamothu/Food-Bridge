"""Matching queue integration; production candidate/ranking adapters remain Rushitha's work."""

from foodbridge.agents.celery_app import celery_app


@celery_app.task(name="foodbridge.matching.probe")
def probe() -> dict[str, str]:
    """Diagnostic only: verifies registration, not business functionality."""
    return {"worker": "matching", "status": "registered"}


def execute(step_id):
    from uuid import UUID

    from foodbridge.agents.orchestrator.service import WorkflowService
    from foodbridge.integrations.workflow import matching_gateway
    from foodbridge.settings import Settings

    settings = Settings()
    WorkflowService(
        settings.database_url, allow_synthetic=settings.enable_local_workflow_demo
    ).run_step(UUID(step_id), matching_gateway(settings))


@celery_app.task(name="foodbridge.matching.prepare", acks_late=True)
def prepare(step_id: str):
    execute(step_id)


@celery_app.task(name="foodbridge.matching.rank", acks_late=True)
def rank(step_id: str):
    execute(step_id)
