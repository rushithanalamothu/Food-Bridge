"""Recoverable maintenance loop. Duplicate instances are safe under database leases."""

import logging
import time

from kombu.exceptions import OperationalError as BrokerError
from sqlalchemy.exc import OperationalError

from foodbridge.agents.celery_app import celery_app
from foodbridge.agents.orchestrator.relay import dispatch_pending
from foodbridge.agents.orchestrator.service import WorkflowService
from foodbridge.api.stream import publish_stream
from foodbridge.settings import Settings

logger = logging.getLogger(__name__)


def tick(settings):
    dispatch_pending(settings)
    coordinator = WorkflowService(
        settings.database_url, allow_synthetic=settings.enable_local_workflow_demo
    )
    coordinator.recover_intake()
    for identifier in coordinator.sweep():
        # Publication failure leaves the step due in PostgreSQL for the next sweep.
        celery_app.send_task(
            "foodbridge.orchestrator.plan_step", args=[str(identifier)], retry=False
        )
    celery_app.send_task("foodbridge.reservation.deliver_notifications", retry=False)
    publish_stream(settings.database_url)


def main():
    settings = Settings()
    while True:
        try:
            tick(settings)
        except (OperationalError, BrokerError, OSError):
            logger.warning("workflow_maintenance_dependency_unavailable")
        time.sleep(2)


if __name__ == "__main__":
    main()
