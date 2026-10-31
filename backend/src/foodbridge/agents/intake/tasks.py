"""Intake diagnostics and idempotent eligibility evaluation worker."""

from sqlalchemy.exc import OperationalError

from foodbridge.agents.celery_app import celery_app


@celery_app.task(name="foodbridge.intake.probe")
def probe() -> dict[str, str]:
    """Diagnostic only: verifies registration, not business functionality."""
    return {"worker": "intake", "status": "registered"}


@celery_app.task(
    name="foodbridge.intake.evaluate",
    bind=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def evaluate_donation(self, evaluation_id: str):
    """Messages contain a persisted batch ID only; DB transaction deduplicates effects."""
    from uuid import UUID

    from foodbridge.agents.intake.service import IntakeService
    from foodbridge.settings import Settings

    settings = Settings()
    result = IntakeService(
        settings.database_url, allow_synthetic=settings.enable_local_intake_demo
    ).process_evaluation(UUID(evaluation_id))
    return {"evaluation_id": evaluation_id, "status": result.status if result else "not_found"}
