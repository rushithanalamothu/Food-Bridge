"""Four queues, one shared build. Business task handlers are deliberately not stubbed as success."""

from celery import Celery
from kombu import Queue

from foodbridge.settings import Settings

settings = Settings()
celery_app = Celery(
    "foodbridge",
    broker=settings.redis_url,
    include=[
        f"foodbridge.agents.{name}.tasks"
        for name in ("orchestrator", "intake", "matching", "reservation")
    ],
)
celery_app.conf.update(
    task_default_queue="orchestrator",
    task_queues=[Queue(name) for name in ("orchestrator", "intake", "matching", "reservation")],
    task_routes={
        f"foodbridge.{name}.*": {"queue": name}
        for name in ("orchestrator", "intake", "matching", "reservation")
    },
    task_create_missing_queues=False,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=45,
    task_time_limit=60,
    broker_transport_options={"visibility_timeout": 300},
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    enable_utc=True,
)
