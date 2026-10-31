"""Bounded-label intake metrics and allowlisted JSON diagnostics; no donor text or secrets."""

import json
import logging
from contextlib import contextmanager
from time import perf_counter
from uuid import UUID

from prometheus_client import CollectorRegistry, Counter, Histogram

registry = CollectorRegistry()
requests = Counter(
    "intake_requests_total", "Intake HTTP requests by status", ["status"], registry=registry
)
decisions = Counter(
    "eligibility_decisions_total",
    "Donation and candidate outcomes",
    ["subject", "outcome"],
    registry=registry,
)
latency = Histogram(
    "validation_latency_seconds",
    "Intake stage elapsed seconds",
    ["stage"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 20),
    registry=registry,
)
duplicates = Counter("duplicate_idempotency_total", "Recognized request replays", registry=registry)
publication_retries = Counter(
    "eligible_event_retry_total", "Intake publication failures", registry=registry
)
model_calls = Counter(
    "intake_model_calls_total", "Extraction attempts", ["outcome"], registry=registry
)
review_fields = Counter(
    "intake_review_fields_total",
    "Missing or unsupported source evidence",
    ["reason"],
    registry=registry,
)
logger = logging.getLogger("foodbridge.intake")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.propagate = False


def record(
    event: str,
    *,
    request_id: UUID | None = None,
    donation_id: UUID | None = None,
    evaluation_id: UUID | None = None,
    event_id: UUID | None = None,
    outcome: str,
    duration_ms: float = 0,
    model: str | None = None,
    policy_version: str | None = None,
    attempts: int | None = None,
    reason_codes: list[str] | None = None,
) -> None:
    """Only application-controlled metadata. Never pass provider exceptions or request values."""
    logger.info(
        json.dumps(
            {
                "event": event,
                "component": "intake",
                "operation": event.split(".")[0],
                "request_id": str(request_id) if request_id else None,
                "donation_id": str(donation_id) if donation_id else None,
                "evaluation_id": str(evaluation_id) if evaluation_id else None,
                "event_id": str(event_id) if event_id else None,
                "outcome": outcome,
                "duration_ms": round(duration_ms, 3),
                "model_version": model,
                "ruleset_version": policy_version,
                "attempts": attempts,
                "reason_codes": reason_codes,
            },
            sort_keys=True,
        )
    )


@contextmanager
def timed(stage: str):
    start = perf_counter()
    try:
        yield
    finally:
        latency.labels(stage).observe(perf_counter() - start)
