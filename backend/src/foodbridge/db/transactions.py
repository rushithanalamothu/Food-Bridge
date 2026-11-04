"""Shared transactional outbox and command-receipt primitives."""

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from foodbridge.db.models import IdempotencyRecord, OutboxEvent
from foodbridge.domain.contracts import EventEnvelope
from foodbridge.domain.errors import AppError
from foodbridge.observability import duplicates


def enqueue_event(
    session,
    aggregate_id: UUID,
    version: int,
    event_type: str,
    now: datetime,
    correlation_id: UUID,
    payload: dict,
) -> OutboxEvent:
    envelope = EventEnvelope(
        event_id=uuid4(),
        aggregate_id=aggregate_id,
        aggregate_version=version,
        event_type=event_type,
        occurred_at=now,
        correlation_id=correlation_id,
        payload=payload,
    )
    row = OutboxEvent(
        event_id=envelope.event_id,
        aggregate_id=aggregate_id,
        aggregate_version=version,
        event_type=event_type,
        envelope=envelope.model_dump(mode="json"),
    )
    session.add(row)
    return row


def idempotency(session, actor_id: UUID, action: str, key: UUID, body: dict):
    identity = f"{actor_id}:{action}:{key}"
    lock = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    record = session.get(IdempotencyRecord, (actor_id, action, key))
    legacy_digest = None
    if action == "donations" and body.get("donation", {}).get("packaging_type") is None:
        # Receipts created before optional packaging existed used the earlier canonical DTO.
        legacy_body = {**body, "donation": dict(body["donation"])}
        legacy_body["donation"].pop("packaging_type", None)
        legacy_digest = hashlib.sha256(json.dumps(legacy_body, sort_keys=True).encode()).hexdigest()
    if record and record.request_hash not in {digest, legacy_digest}:
        raise AppError(
            "idempotency_key_reused", "This request key was used for different details.", 409
        )
    if record:
        duplicates.inc()
    return record, digest


def remember_response(session, actor_id, action, key, digest, response, now):
    session.add(
        IdempotencyRecord(
            actor_id=actor_id,
            action=action,
            key=key,
            request_hash=digest,
            response=response,
            created_at=now,
        )
    )
