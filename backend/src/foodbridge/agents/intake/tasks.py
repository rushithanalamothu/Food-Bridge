"""Intake worker entry point. Add real task handlers after contracts are reviewed."""

from foodbridge.agents.celery_app import celery_app


@celery_app.task(name="foodbridge.intake.probe")
def probe() -> dict[str, str]:
    """Diagnostic only: verifies registration, not business functionality."""
    return {"worker": "intake", "status": "registered"}
