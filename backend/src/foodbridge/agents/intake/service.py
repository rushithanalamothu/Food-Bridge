"""Persisted intake application service; owns transactions and version/idempotency guards."""

import base64
import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text

from foodbridge.agents.intake.config import load_policy
from foodbridge.agents.intake.policy import evaluate, urgency, validate_confirmation
from foodbridge.db.models import (
    Donation,
    DonationDraft,
    IdempotencyRecord,
    IntakeEvaluation,
    OutboxEvent,
    StatusHistory,
)
from foodbridge.db.session import session_factory
from foodbridge.domain.contracts import DonationInput, DonationRead, EventEnvelope
from foodbridge.domain.errors import AppError
from foodbridge.domain.intake import (
    DonationSubmit,
    DonorIdentity,
    DraftCreate,
    DraftRead,
    EligibilityBatch,
    EligibilityResult,
    EvaluationRead,
    ExtractionResult,
    IntakeDonationRead,
    IntakeHandoff,
)
from foodbridge.observability import decisions, duplicates, record, timed


def utcnow() -> datetime:
    return datetime.now(UTC)


def _event(
    session,
    aggregate_id: UUID,
    version: int,
    event_type: str,
    now: datetime,
    correlation_id: UUID,
    payload: dict,
) -> None:
    envelope = EventEnvelope(
        event_id=uuid4(),
        aggregate_id=aggregate_id,
        aggregate_version=version,
        event_type=event_type,
        occurred_at=now,
        correlation_id=correlation_id,
        payload=payload,
    )
    session.add(
        OutboxEvent(
            event_id=envelope.event_id,
            aggregate_id=aggregate_id,
            aggregate_version=version,
            event_type=event_type,
            envelope=envelope.model_dump(mode="json"),
        )
    )


def _idempotency(session, actor_id: UUID, action: str, key: UUID, body: dict):
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


def _remember(session, actor_id, action, key, digest, response, now):
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


def donation_view(row: Donation, now: datetime) -> IntakeDonationRead:
    value = DonationRead(
        **row.confirmed_data,
        id=row.id,
        donor_organization_id=row.donor_organization_id,
        status=row.status,
        version=row.version,
        created_at=row.created_at,
    )
    return IntakeDonationRead(donation=value, urgency=urgency(value, now, load_policy()))


def _draft_view(session, row: DonationDraft) -> DraftRead:
    donation_id = session.scalar(select(Donation.id).where(Donation.draft_id == row.id))
    return DraftRead(
        id=row.id,
        donor_organization_id=row.donor_organization_id,
        description=row.description,
        pickup_location=row.pickup_location,
        extraction=row.extraction,
        status=row.status,
        version=row.version,
        created_at=row.created_at,
        donation_id=donation_id,
    )


class IntakeService:
    def __init__(self, database_url: str, clock=utcnow, *, allow_synthetic: bool = False):
        self.sessions = session_factory(database_url)
        self.clock = clock
        self.allow_synthetic = allow_synthetic
        self.policy = load_policy()

    def create_draft(
        self, actor: DonorIdentity, request: DraftCreate, extraction: ExtractionResult, key: UUID
    ) -> DraftRead:
        now = self.clock()
        with self.sessions.begin() as session:
            old, digest = _idempotency(
                session, actor.user_id, "drafts", key, request.model_dump(mode="json")
            )
            if old:
                return DraftRead.model_validate(old.response)
            if len(request.description) > self.policy.max_description_length:
                raise AppError("description_too_long", "Shorten the food description.")
            draft = DonationDraft(
                id=uuid4(),
                donor_organization_id=actor.organization_id,
                description=request.description,
                pickup_location=request.pickup_location.model_dump(mode="json"),
                extraction=extraction.model_dump(mode="json"),
                created_at=now,
                version=1,
                status="review_required",
            )
            session.add(draft)
            session.flush()
            view = _draft_view(session, draft)
            _remember(
                session, actor.user_id, "drafts", key, digest, view.model_dump(mode="json"), now
            )
            return view

    def replay_draft(
        self, actor: DonorIdentity, request: DraftCreate, key: UUID
    ) -> DraftRead | None:
        """Avoid another model call for a completed request; concurrent first calls may overlap."""
        with self.sessions.begin() as session:
            old, _ = _idempotency(
                session, actor.user_id, "drafts", key, request.model_dump(mode="json")
            )
            return DraftRead.model_validate(old.response) if old else None

    def get_draft(self, actor: DonorIdentity, draft_id: UUID) -> DraftRead:
        with self.sessions() as session:
            row = session.scalar(
                select(DonationDraft).where(
                    DonationDraft.id == draft_id,
                    DonationDraft.donor_organization_id == actor.organization_id,
                )
            )
            if row is None:
                raise AppError("not_found", "Draft not found.", 404)
            return _draft_view(session, row)

    def submit(
        self, actor: DonorIdentity, request: DonationSubmit, key: UUID, correlation_id: UUID
    ) -> IntakeDonationRead:
        started = perf_counter()
        now = self.clock()
        with self.sessions.begin() as session:
            old, digest = _idempotency(
                session, actor.user_id, "donations", key, request.model_dump(mode="json")
            )
            if old:
                return IntakeDonationRead.model_validate(old.response)
            draft = session.scalar(
                select(DonationDraft)
                .where(
                    DonationDraft.id == request.draft_id,
                    DonationDraft.donor_organization_id == actor.organization_id,
                )
                .with_for_update()
            )
            if draft is None:
                raise AppError("not_found", "Draft not found.", 404)
            if draft.status != "review_required" or draft.version != request.expected_draft_version:
                raise AppError(
                    "stale_version", "This draft changed or was already posted. Refresh it.", 409
                )
            if request.donation.description != draft.description:
                raise AppError(
                    "description_changed", "Create a new draft after changing the description.", 409
                )
            try:
                validate_confirmation(request.donation, now, self.policy)
            except ValueError as exc:
                raise AppError(
                    str(exc),
                    {
                        "description_too_long": "Shorten the food description.",
                        "required_detail_missing": "Complete the required donation details.",
                        "pickup_deadline_passed": "Pickup has ended. Update the window.",
                        "quantity_precision_or_range": "Use up to three decimals for weight.",
                        "allergens_need_review": "Use standard allergen names, such as soy.",
                        "conflicting_dietary_claims": "Correct the conflicting diet/allergens.",
                    }.get(str(exc), "Check the confirmed donation details."),
                    422,
                ) from exc
            value = request.donation
            row = Donation(
                id=uuid4(),
                draft_id=draft.id,
                donor_organization_id=actor.organization_id,
                confirmed_data=value.model_dump(mode="json"),
                quantity_kg=value.quantity_kg,
                pickup_start=value.pickup_window.start,
                pickup_end=value.pickup_window.end,
                safe_use_by=value.safe_use_by,
                status="submitted",
                version=1,
                matching_round=1,
                created_at=now,
            )
            session.add(row)
            session.flush()
            draft.status, draft.version = "confirmed", draft.version + 1
            session.add(
                StatusHistory(
                    donation_id=row.id,
                    aggregate_version=1,
                    previous_status=None,
                    next_status="submitted",
                    actor_id=actor.user_id,
                    reason="donor_confirmed",
                    correlation_id=correlation_id,
                    occurred_at=now,
                )
            )
            _event(
                session,
                row.id,
                1,
                "donation.submitted.v1",
                now,
                correlation_id,
                {"matching_round": 1},
            )
            view = donation_view(row, now)
            _remember(
                session, actor.user_id, "donations", key, digest, view.model_dump(mode="json"), now
            )
        record(
            "donation.persisted",
            request_id=correlation_id,
            donation_id=row.id,
            outcome="submitted",
            duration_ms=(perf_counter() - started) * 1000,
            policy_version=self.policy.version,
        )
        return view

    def get_donation(self, actor: DonorIdentity, donation_id: UUID) -> IntakeDonationRead:
        with self.sessions() as session:
            row = session.scalar(
                select(Donation).where(
                    Donation.id == donation_id,
                    Donation.donor_organization_id == actor.organization_id,
                )
            )
            if row is None:
                raise AppError("not_found", "Donation not found.", 404)
            return donation_view(row, self.clock())

    def list_donations(self, actor: DonorIdentity, limit: int, cursor: str | None):
        with self.sessions() as session:
            query = select(Donation).where(Donation.donor_organization_id == actor.organization_id)
            if cursor:
                try:
                    if len(cursor) > 300:
                        raise ValueError("cursor too long")
                    timestamp, identifier = json.loads(base64.urlsafe_b64decode(cursor).decode())
                    timestamp, identifier = datetime.fromisoformat(timestamp), UUID(identifier)
                    if timestamp.tzinfo is None:
                        raise ValueError("naive cursor")
                except (ValueError, TypeError, UnicodeError) as exc:
                    raise AppError("invalid_cursor", "Refresh the donation list.") from exc
                query = query.where(
                    or_(
                        Donation.created_at < timestamp,
                        and_(Donation.created_at == timestamp, Donation.id < identifier),
                    )
                )
            rows = list(
                session.scalars(
                    query.order_by(Donation.created_at.desc(), Donation.id.desc()).limit(limit + 1)
                )
            )
            next_cursor = None
            if len(rows) > limit:
                last = rows[limit - 1]
                next_cursor = base64.urlsafe_b64encode(
                    json.dumps([last.created_at.isoformat(), str(last.id)]).encode()
                ).decode()
            return {
                "items": [donation_view(row, self.clock()) for row in rows[:limit]],
                "next_cursor": next_cursor,
            }

    def request_evaluation(
        self,
        actor: DonorIdentity,
        batch: EligibilityBatch,
        key: UUID,
        correlation_id: UUID,
        *,
        demo_key: bool = False,
    ) -> EvaluationRead:
        now = self.clock()
        with self.sessions.begin() as session:
            old, digest = _idempotency(
                session,
                actor.user_id,
                "intake-evaluations",
                key,
                (
                    {"donation_id": str(batch.donation_id)}
                    if demo_key
                    else batch.model_dump(mode="json")
                ),
            )
            if old:
                return EvaluationRead.model_validate(old.response)
            donation = session.scalar(
                select(Donation).where(
                    Donation.id == batch.donation_id,
                    Donation.donor_organization_id == actor.organization_id,
                )
            )
            if donation is None:
                raise AppError("not_found", "Donation not found.", 404)
            if donation.version != batch.expected_donation_version:
                raise AppError(
                    "stale_version", "Refresh the donation before requesting eligibility.", 409
                )
            row = IntakeEvaluation(
                id=uuid4(),
                donation_id=donation.id,
                donor_organization_id=actor.organization_id,
                batch=batch.model_dump(mode="json"),
                status="pending",
                created_at=now,
            )
            session.add(row)
            _event(
                session,
                row.id,
                1,
                "intake.evaluation_requested.v1",
                now,
                correlation_id,
                {"donation_id": str(donation.id)},
            )
            view = EvaluationRead(
                id=row.id, donation_id=donation.id, status="pending", synthetic=batch.synthetic
            )
            _remember(
                session,
                actor.user_id,
                "intake-evaluations",
                key,
                digest,
                view.model_dump(mode="json"),
                now,
            )
            return view

    def request_demo_evaluation(self, actor, batch, key, correlation_id):
        return self.request_evaluation(actor, batch, key, correlation_id, demo_key=True)

    def get_evaluation(self, actor: DonorIdentity, identifier: UUID) -> EvaluationRead:
        with self.sessions() as session:
            row = session.scalar(
                select(IntakeEvaluation).where(
                    IntakeEvaluation.id == identifier,
                    IntakeEvaluation.donor_organization_id == actor.organization_id,
                )
            )
            if row is None:
                raise AppError("not_found", "Evaluation not found.", 404)
            return self._evaluation_view(row)

    @staticmethod
    def _evaluation_view(row) -> EvaluationRead:
        return EvaluationRead(
            id=row.id,
            donation_id=row.donation_id,
            status=row.status,
            synthetic=row.batch["synthetic"],
            result=row.result,
            failure_code=row.failure_code,
        )

    def process_evaluation(self, identifier: UUID) -> EvaluationRead | None:
        """One short DB transaction; duplicate deliveries observe the completed result."""
        started = perf_counter()
        now = self.clock()
        with self.sessions.begin() as session:
            row = session.get(IntakeEvaluation, identifier, with_for_update=True)
            if row is None:
                return None
            if row.status != "pending":
                return self._evaluation_view(row)
            donation = session.get(Donation, row.donation_id, with_for_update=True)
            batch = EligibilityBatch.model_validate(row.batch)
            if donation.version != batch.expected_donation_version or donation.status not in {
                "submitted",
                "matching",
                "offered",
            }:
                row.status, row.failure_code = "stale", "donation_state_changed"
            elif batch.synthetic and not self.allow_synthetic:
                row.status, row.failure_code = "failed", "synthetic_evaluation_disabled"
            else:
                with timed("eligibility"):
                    result = evaluate(
                        DonationInput.model_validate(donation.confirmed_data),
                        batch,
                        now,
                        self.policy,
                    )
                row.result, row.status = result.model_dump(mode="json"), "completed"
                source_event = session.scalar(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id == row.id,
                        OutboxEvent.event_type == "intake.evaluation_requested.v1",
                    )
                )
                correlation_id = (
                    UUID(source_event.envelope["correlation_id"]) if source_event else uuid4()
                )
                _event(
                    session,
                    row.id,
                    1,
                    "intake.evaluated.v1",
                    now,
                    correlation_id,
                    {
                        "donation_id": str(donation.id),
                        "donation_version": donation.version,
                        "eligible_count": sum(d.eligible for d in result.decisions),
                        "donation_decision": result.donation_decision,
                        "synthetic": batch.synthetic,
                    },
                )
            view = self._evaluation_view(row)
        if view.result:
            decisions.labels("donation", view.result.donation_decision).inc()
            for decision in view.result.decisions:
                decisions.labels("candidate", "eligible" if decision.eligible else "rejected").inc()
        record(
            "validation.completed",
            request_id=correlation_id if view.result else None,
            donation_id=donation.id,
            evaluation_id=identifier,
            outcome=view.status,
            duration_ms=(perf_counter() - started) * 1000,
            reason_codes=sorted(
                {reason for decision in view.result.decisions for reason in decision.reasons}
            )
            if view.result
            else [],
            policy_version=self.policy.version,
        )
        return view

    def get_handoff(self, identifier: UUID) -> IntakeHandoff:
        """Internal Orchestrator port: confirmed donation plus revalidated candidate snapshots.

        No ranking, state transition, publication or reservation occurs here. Downstream
        transactions must still recheck versions and current capacity before accepting.
        """
        with self.sessions() as session:
            row = session.get(IntakeEvaluation, identifier)
            if row is None or row.status != "completed":
                raise AppError(
                    "evaluation_not_ready", "Eligibility evaluation is not complete.", 409
                )
            donation = session.get(Donation, row.donation_id)
            batch = EligibilityBatch.model_validate(row.batch)
            saved = EligibilityResult.model_validate(row.result)
            if (
                donation.version != batch.expected_donation_version
                or donation.status not in {"submitted", "matching", "offered"}
                or saved.policy_version != self.policy.version
                or (batch.synthetic and not self.allow_synthetic)
            ):
                raise AppError("stale_evaluation", "Request a new eligibility evaluation.", 409)
            now = self.clock()
            value = donation_view(donation, now).donation
            result = evaluate(value, batch, now, self.policy)
            if result.donation_decision != "eligible":
                raise AppError(
                    "stale_evaluation", "The donation needs a new validation or donor review.", 409
                )
            eligible = {d.recipient_organization_id for d in result.decisions if d.eligible}
            return IntakeHandoff(
                evaluation_id=row.id,
                donation=value,
                result=result,
                eligible_candidates=[
                    c for c in batch.candidates if c.recipient.organization_id in eligible
                ],
            )
