"""Database-backed coordinator. Calculations run outside transactions; results use fenced leases."""

import random
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import String, cast, exists, or_, select

from foodbridge.agents.intake.service import IntakeService, utcnow
from foodbridge.agents.reservation.service import ReservationService
from foodbridge.db.models import Donation, IntakeEvaluation, OutboxEvent
from foodbridge.db.session import session_factory
from foodbridge.db.transactions import enqueue_event as _event
from foodbridge.db.workflow import (
    audience,
    command,
    conflict,
    locked_donation,
    release_all,
    require_role,
    require_version,
    snapshot,
    transition,
)
from foodbridge.db.workflow_models import (
    Assignment,
    ConsumerReceipt,
    Driver,
    MatchOffer,
    Notification,
    Reservation,
    TaskFailure,
    WorkflowStep,
)
from foodbridge.domain.contracts import MatchRecommendation
from foodbridge.domain.errors import AppError
from foodbridge.domain.intake import EligibilityBatch
from foodbridge.integrations.workflow import DependencyUnavailable

TERMINAL = {"delivered", "no_match", "expired", "cancelled", "failed"}
MAX_ATTEMPTS = 3
LEASE_SECONDS = 75


def provider_call(callback, *args):
    """Keep arbitrary provider exception strings out of Celery's task logger."""
    try:
        return callback(*args)
    except (
        DependencyUnavailable,
        OSError,
        TimeoutError,
        AppError,
        ValueError,
        KeyError,
        TypeError,
    ):
        raise
    except Exception:
        raise DependencyUnavailable("provider_failure") from None


class WorkflowService:
    def __init__(self, database_url, clock=utcnow, *, allow_synthetic=False):
        self.url, self.clock, self.allow_synthetic = database_url, clock, allow_synthetic
        self.sessions = session_factory(database_url)
        self.intake = IntakeService(database_url, clock, allow_synthetic=allow_synthetic)
        self.reservation = ReservationService(database_url, clock, allow_synthetic=allow_synthetic)

    def schedule(self, session, donation, kind, now, data=None):
        identity = (donation.id, donation.matching_round, kind, donation.version)
        existing = session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.donation_id == identity[0],
                WorkflowStep.matching_round == identity[1],
                WorkflowStep.kind == kind,
                WorkflowStep.input_version == identity[3],
            )
        )
        if existing:
            return existing
        row = WorkflowStep(
            id=uuid4(),
            donation_id=donation.id,
            matching_round=donation.matching_round,
            kind=kind,
            input_version=donation.version,
            data=data or {},
            next_attempt_at=now,
            deadline=min(donation.pickup_end, donation.safe_use_by),
        )
        session.add(row)
        session.flush()
        return row

    def consume(self, event_id):
        """Commit receipt, state application and next step together."""
        from foodbridge.agents.orchestrator.agent import DISPATCH_EVENT, OrchestratorAgent

        with self.sessions() as session:
            row = session.get(OutboxEvent, event_id)
            is_dispatch = row is not None and row.event_type == DISPATCH_EVENT
        if is_dispatch:
            from foodbridge.settings import Settings

            OrchestratorAgent(Settings(database_url=self.url), self.clock).dispatch(event_id)
            return
        with self.sessions.begin() as session:
            event = session.get(OutboxEvent, event_id, with_for_update=True)
            if event is None or session.get(ConsumerReceipt, ("orchestrator", event_id)):
                return
            now = self.clock()
            payload = event.envelope["payload"]
            identifier = (
                UUID(payload["donation_id"]) if payload.get("donation_id") else event.aggregate_id
            )
            donation = session.get(Donation, identifier, with_for_update=True)
            if donation:
                if (
                    donation.status not in TERMINAL
                    and now >= min(donation.pickup_end, donation.safe_use_by)
                    and donation.status != "picked_up"
                ):
                    release_all(session, donation, failure=True)
                    transition(
                        session,
                        donation,
                        "expired",
                        "deadline_reached",
                        now,
                        UUID(event.envelope["correlation_id"]),
                    )
                elif (
                    event.event_type == "donation.submitted.v1"
                    and donation.status == "submitted"
                    and donation.version == event.aggregate_version
                ):
                    transition(
                        session,
                        donation,
                        "matching",
                        "intake_dispatch",
                        now,
                        UUID(event.envelope["correlation_id"]),
                    )
                    self.schedule(session, donation, "eligibility", now)
                elif (
                    event.event_type == "intake.evaluated.v1"
                    and donation.status == "matching"
                    and payload.get("donation_version") == donation.version
                ):
                    evaluation = session.get(IntakeEvaluation, event.aggregate_id)
                    if evaluation and evaluation.status == "completed":
                        decision = evaluation.result.get("donation_decision")
                        if decision == "needs_review":
                            transition(
                                session,
                                donation,
                                "needs_review",
                                "intake_review_required",
                                now,
                                UUID(event.envelope["correlation_id"]),
                            )
                        elif decision != "eligible":
                            transition(
                                session,
                                donation,
                                "failed",
                                "intake_rejected",
                                now,
                                UUID(event.envelope["correlation_id"]),
                            )
                        else:
                            self.schedule(
                                session,
                                donation,
                                "matching",
                                now,
                                {"evaluation_id": str(evaluation.id)},
                            )
                elif donation.version == event.aggregate_version:
                    if donation.status == "matching":
                        self.schedule(session, donation, "eligibility", now)
                    elif donation.status == "reserved":
                        self.schedule(session, donation, "assignment", now)
                # Only committed, scoped status events request notifications.
                if event.audience:
                    self.notifications(session, event, donation, now)
            session.add(
                ConsumerReceipt(consumer="orchestrator", event_id=event_id, completed_at=now)
            )

    @staticmethod
    def notifications(session, event, donation, now):
        from foodbridge.db.models import Membership, User

        users = set()
        for target in event.audience:
            if "user_id" in target:
                users.add(UUID(target["user_id"]))
            elif target["role"] != "operator":
                users.update(
                    session.scalars(
                        select(Membership.user_id)
                        .join(User, User.id == Membership.user_id)
                        .where(
                            Membership.organization_id == UUID(target["organization_id"]),
                            Membership.role == target["role"],
                            User.active.is_(True),
                        )
                    )
                )
        for user in users:
            session.add(
                Notification(
                    id=uuid4(),
                    event_id=event.event_id,
                    donation_id=donation.id,
                    user_id=user,
                    template=event.event_type,
                    next_attempt_at=now,
                )
            )

    def claim(self, identifier, dispatch_token=None):
        with self.sessions.begin() as session:
            # Every workflow write takes the donation lock before the step lock.
            initial = session.get(WorkflowStep, identifier)
            if not initial:
                return None
            donation = locked_donation(session, initial.donation_id)
            row = session.get(
                WorkflowStep, identifier, with_for_update=True, populate_existing=True
            )
            now = self.clock()
            if (
                row.status not in {"pending", "running"}
                or row.next_attempt_at > now
                or (row.status == "running" and row.lease_until > now)
            ):
                return None
            planning = row.data.get("orchestrator")
            if (
                planning
                and (
                    dispatch_token is None or planning.get("dispatch_token") != str(dispatch_token)
                )
            ) or (dispatch_token is not None and not planning):
                return None
            if (
                donation.version != row.input_version
                or donation.matching_round != row.matching_round
                or donation.status in TERMINAL
            ):
                row.status = "stale"
                return None
            if now >= row.deadline:
                row.status = "stale"
                return None
            if row.attempts >= MAX_ATTEMPTS + row.data.get("extra_attempts", 0):
                self.fail(session, row, "worker_lease_exhausted", now)
                return None
            row.status, row.lease_token = "running", uuid4()
            row.lease_until = now + timedelta(seconds=LEASE_SECONDS)
            row.attempts += 1
            if planning:
                row.data = {
                    **row.data,
                    "orchestrator": {**planning, "status": "executing", "lease_until": None},
                }
            excluded = set(
                session.scalars(
                    select(MatchOffer.recipient_organization_id).where(
                        MatchOffer.donation_id == donation.id,
                        MatchOffer.status.in_(["declined", "expired", "accepted", "superseded"]),
                    )
                )
            )
            # During assignment the accepted recipient is retained.
            excluded_drivers = set(
                session.scalars(
                    select(Assignment.driver_id).where(
                        Assignment.donation_id == donation.id,
                        Assignment.status.in_(["declined", "released"]),
                    )
                )
            )
            return row, snapshot(donation, now), excluded, excluded_drivers

    def run_step(self, identifier, gateway, *, dispatch_token=None):
        claim = self.claim(identifier, dispatch_token)
        if claim is None:
            return
        row, donation, excluded, excluded_drivers = claim
        try:
            if row.kind in {"eligibility", "assignment"}:
                result = provider_call(
                    gateway.candidates,
                    donation,
                    excluded if row.kind == "eligibility" else set(),
                    excluded_drivers,
                )
                result = EligibilityBatch.model_validate(result)
                if (
                    result.donation_id != donation.id
                    or result.expected_donation_version != donation.version
                    or (result.synthetic and not self.allow_synthetic)
                ):
                    raise AppError(
                        "invalid_candidate_result",
                        "Candidate producer returned an invalid version.",
                        409,
                    )
                if (
                    any(c.recipient.organization_id in excluded for c in result.candidates)
                    and row.kind == "eligibility"
                ):
                    raise AppError(
                        "excluded_recipient",
                        "Candidate producer returned an excluded recipient.",
                        409,
                    )
                if any(c.driver and c.driver.id in excluded_drivers for c in result.candidates):
                    raise AppError(
                        "excluded_driver", "Candidate producer reused a declined driver.", 409
                    )
            elif row.kind == "matching":
                handoff = self.intake.get_handoff(UUID(row.data["evaluation_id"]))
                if any("route_stale" in d.reasons for d in handoff.result.decisions):
                    raise AppError("stale_evaluation", "Fresh route facts are required.", 409)
                result = provider_call(gateway.rank, handoff, row.matching_round)
                if result is not None:
                    result = MatchRecommendation.model_validate(result)
            else:
                raise AppError("unknown_step", "Unknown workflow step.")
            self.finish(row, result)
        except DependencyUnavailable as error:
            self.retry(row, error.code)
        except (TimeoutError, OSError):
            self.retry(row, "provider_unavailable")
        except AppError as error:
            if row.kind == "matching" and error.code in {
                "stale_evaluation",
                "recipient_profile_changed",
                "driver_changed",
                "eligibility_changed",
                "recipient_unavailable",
            }:
                self.refresh(row)
            elif error.code in {
                "stale_evaluation",
                "evaluation_not_ready",
                "driver_busy",
                "driver_infeasible",
            }:
                self.retry(row, error.code)
            else:
                self.retry(row, "invalid_workflow_result", terminal=True)
        except (ValueError, KeyError, TypeError):
            self.retry(row, "invalid_workflow_result", terminal=True)

    def refresh(self, claimed):
        with self.sessions.begin() as session:
            donation = locked_donation(session, claimed.donation_id)
            row = session.get(WorkflowStep, claimed.id, with_for_update=True)
            if row.status != "running" or row.lease_token != claimed.lease_token:
                return
            row.status = "stale"
            if donation.status != "matching" or donation.version != row.input_version:
                return
            now = self.clock()
            if now >= row.deadline:
                return
            if donation.matching_round >= 10:
                self.fail(session, row, "revalidation_exhausted", now)
                transition(session, donation, "failed", "revalidation_exhausted", now, row.id)
            else:
                donation.matching_round += 1
                transition(session, donation, "matching", "facts_changed_revalidate", now, row.id)
                self.schedule(session, donation, "eligibility", now)

    def finish(self, claimed, result):
        with self.sessions.begin() as session:
            donation = locked_donation(session, claimed.donation_id)
            row = session.get(WorkflowStep, claimed.id, with_for_update=True)
            now = self.clock()
            if (
                row.status != "running"
                or row.lease_token != claimed.lease_token
                or row.lease_until <= now
            ):
                return
            if (
                donation.version != row.input_version
                or donation.matching_round != row.matching_round
                or donation.status in TERMINAL
                or now >= row.deadline
            ):
                row.status = "stale"
                return
            correlation = row.id
            if row.kind == "eligibility":
                evaluation = IntakeEvaluation(
                    id=uuid4(),
                    donor_organization_id=donation.donor_organization_id,
                    donation_id=donation.id,
                    batch=result.model_dump(mode="json"),
                    created_at=now,
                )
                session.add(evaluation)
                session.flush()
                row.data = {**row.data, "evaluation_id": str(evaluation.id)}
                _event(
                    session,
                    evaluation.id,
                    1,
                    "intake.evaluation_requested.v1",
                    now,
                    correlation,
                    {"donation_id": str(donation.id), "donation_version": donation.version},
                )
            elif row.kind == "matching":
                evaluation = session.get(IntakeEvaluation, UUID(row.data["evaluation_id"]))
                batch = EligibilityBatch.model_validate(evaluation.batch)
                eligible = {
                    UUID(x["recipient_organization_id"])
                    for x in evaluation.result["decisions"]
                    if x["eligible"]
                }
                if result is None:
                    if eligible:
                        raise AppError(
                            "invalid_no_match", "Matcher omitted eligible candidates.", 409
                        )
                    transition(
                        session, donation, "no_match", "no_eligible_recipient", now, correlation
                    )
                else:
                    if (
                        result.donation_id != donation.id
                        or result.donation_version != donation.version
                        or result.matching_round != donation.matching_round
                        or result.recipient_organization_id not in eligible
                        or result.eligibility_policy_version != self.reservation.policy.version
                    ):
                        raise AppError(
                            "invalid_match",
                            "Matcher returned an invalid candidate or version.",
                            409,
                        )
                    candidate = next(
                        c
                        for c in batch.candidates
                        if c.recipient.organization_id == result.recipient_organization_id
                    )
                    if (
                        candidate.route is None
                        or result.distance_m != candidate.route.distance_m
                        or result.travel_time_s != candidate.route.travel_time_s
                    ):
                        raise AppError("invalid_route", "Matcher changed route facts.", 409)
                    driver = session.get(Driver, candidate.driver.id)
                    offer = MatchOffer(
                        id=result.id,
                        donation_id=donation.id,
                        recipient_organization_id=result.recipient_organization_id,
                        evaluation_id=evaluation.id,
                        matching_round=donation.matching_round,
                        recommendation=result.model_dump(mode="json"),
                        candidate=candidate.model_dump(mode="json"),
                        driver_version=driver.version if driver else 0,
                        expires_at=min(
                            result.offer_expires_at, donation.pickup_end, donation.safe_use_by
                        ),
                        created_at=now,
                    )
                    _, _, decision = self.reservation.eligible(
                        session, donation, offer, now, lock=True
                    )
                    # Accept before the last feasible pickup; reserve rechecks the full route again.
                    if offer.expires_at <= now or decision.pickup_at >= donation.safe_use_by:
                        raise AppError(
                            "invalid_offer_expiry", "Offer cannot be accepted safely.", 409
                        )
                    session.add(offer)
                    transition(
                        session, donation, "offered", "eligible_match_proposed", now, correlation
                    )
                    # Consumers accept using the version of the committed offered snapshot.
                    offer.recommendation = {
                        **offer.recommendation,
                        "donation_version": donation.version,
                    }
            elif row.kind == "assignment":
                reservation = session.scalar(
                    select(Reservation).where(
                        Reservation.donation_id == donation.id, Reservation.status == "active"
                    )
                )
                if not reservation or donation.status != "reserved":
                    row.status = "stale"
                    return
                candidate = next(
                    (
                        c
                        for c in result.candidates
                        if c.recipient.organization_id == reservation.recipient_organization_id
                    ),
                    None,
                )
                if candidate is None or candidate.driver is None:
                    release_all(session, donation)
                    donation.matching_round += 1
                    transition(
                        session, donation, "matching", "no_feasible_driver", now, correlation
                    )
                else:
                    offer = session.get(MatchOffer, reservation.match_id)
                    self.reservation.assign(session, donation, offer, candidate, now, correlation)
            row.status, row.lease_until = "completed", None

    @staticmethod
    def fail(session, row, code, now):
        row.status, row.failure_code, row.lease_until = "failed", code, None
        failure = session.scalar(select(TaskFailure).where(TaskFailure.step_id == row.id))
        if failure:
            failure.code, failure.attempts = code, row.attempts
        else:
            session.add(
                TaskFailure(
                    id=uuid4(),
                    step_id=row.id,
                    donation_id=row.donation_id,
                    code=code,
                    attempts=row.attempts,
                    created_at=now,
                )
            )

    def retry(self, claimed, code, terminal=False):
        with self.sessions.begin() as session:
            donation = locked_donation(session, claimed.donation_id)
            row = session.get(WorkflowStep, claimed.id, with_for_update=True)
            if row.status != "running" or row.lease_token != claimed.lease_token:
                return
            now = self.clock()
            if donation.version != row.input_version or donation.status in TERMINAL:
                row.status = "stale"
            elif terminal or row.attempts >= MAX_ATTEMPTS + row.data.get("extra_attempts", 0):
                self.fail(session, row, code, now)
                if terminal:
                    release_all(session, donation, failure=True)
                    transition(session, donation, "failed", code, now, row.id)
                else:
                    # Exhausted transient dependency work waits for explicit audited replay.
                    _event(
                        session,
                        row.id,
                        row.attempts,
                        "workflow.blocked.v1",
                        now,
                        row.id,
                        {"donation_id": str(donation.id), "reason": code},
                    )
                    session.flush()
                    event = session.scalar(
                        select(OutboxEvent).where(
                            OutboxEvent.aggregate_id == row.id,
                            OutboxEvent.aggregate_version == row.attempts,
                        )
                    )
                    event.audience = audience(session, donation)
            else:
                row.status, row.failure_code, row.lease_until = "pending", code, None
                row.next_attempt_at = min(
                    row.deadline,
                    now + timedelta(seconds=min(30, 2**row.attempts) + random.random()),
                )

    def replay(self, actor, identifier, body, key):
        require_role(actor, "operator")

        def apply(session, now):
            failure = session.get(TaskFailure, identifier)
            donation = locked_donation(session, failure.donation_id) if failure else None
            if donation is None or donation.donor_organization_id != actor.organization_id:
                raise AppError("not_found", "Not found.", 404)
            require_version(donation, body.expected_version)
            row = session.get(WorkflowStep, failure.step_id, with_for_update=True)
            if (
                donation.status in TERMINAL
                or now >= row.deadline
                or row.status != "failed"
                or donation.version != row.input_version
            ):
                conflict("replay_not_allowed")
            # Explicit extra budget, never erase attempts or effect identities.
            row.data = {**row.data, "extra_attempts": row.data.get("extra_attempts", 0) + 3}
            row.status, row.next_attempt_at, row.lease_until = "pending", now, None
            failure.replay_count += 1
            failure.replayed_at, failure.replayed_by = now, actor.user_id
            return {"failure_id": str(identifier), "step_id": str(row.id), "status": "queued"}

        return command(
            self.sessions,
            actor,
            f"POST /api/v1/operations/failures/{identifier}/replay",
            key,
            body.model_dump(mode="json"),
            self.clock,
            apply,
        )

    def sweep(self, limit=100):
        """Multiple schedulers are safe: donation lock and CAS guards fence every transition."""
        now = self.clock()
        offer_due = exists().where(
            MatchOffer.donation_id == Donation.id,
            MatchOffer.status == "offered",
            MatchOffer.expires_at <= now,
        )
        assignment_due = exists().where(
            Assignment.donation_id == Donation.id,
            Assignment.status.in_(["assigned", "accepted"]),
            Assignment.end <= now,
        )
        with self.sessions() as session:
            ids = list(
                session.scalars(
                    select(Donation.id)
                    .where(
                        Donation.status.not_in(TERMINAL | {"draft"}),
                        or_(
                            (Donation.status == "picked_up") & (Donation.safe_use_by <= now),
                            (Donation.status != "picked_up")
                            & or_(
                                Donation.pickup_end <= now,
                                Donation.safe_use_by <= now,
                                offer_due,
                                assignment_due,
                            ),
                        ),
                    )
                    .order_by(Donation.pickup_end, Donation.id)
                    .limit(limit)
                )
            )
        for identifier in ids:
            with self.sessions.begin() as session:
                donation = session.scalar(
                    select(Donation)
                    .where(Donation.id == identifier)
                    .with_for_update(skip_locked=True)
                )
                if donation is None or donation.status in TERMINAL:
                    continue
                if donation.status == "picked_up":
                    if now >= donation.safe_use_by:
                        release_all(session, donation, failure=True)
                        transition(
                            session,
                            donation,
                            "failed",
                            "post_collection_handling_exception",
                            now,
                            uuid4(),
                        )
                    continue
                if now >= min(donation.pickup_end, donation.safe_use_by):
                    release_all(session, donation, failure=True)
                    transition(session, donation, "expired", "deadline_reached", now, uuid4())
                    continue
                if donation.status == "offered":
                    offer = session.scalar(
                        select(MatchOffer).where(
                            MatchOffer.donation_id == donation.id, MatchOffer.status == "offered"
                        )
                    )
                    if offer and offer.expires_at <= now:
                        offer.status, offer.version = "expired", offer.version + 1
                        donation.matching_round += 1
                        transition(session, donation, "matching", "offer_expired", now, uuid4())
                if donation.status == "pickup_assigned":
                    assignment = session.scalar(
                        select(Assignment).where(
                            Assignment.donation_id == donation.id,
                            Assignment.status.in_(["assigned", "accepted"]),
                        )
                    )
                    if assignment and assignment.end <= now:
                        assignment.status, assignment.version = "released", assignment.version + 1
                        transition(
                            session, donation, "reserved", "assignment_timed_out", now, uuid4()
                        )
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(WorkflowStep.id)
                    .where(
                        or_(
                            WorkflowStep.status == "pending",
                            (WorkflowStep.status == "running") & (WorkflowStep.lease_until <= now),
                        ),
                        WorkflowStep.next_attempt_at <= now,
                    )
                    .order_by(WorkflowStep.deadline, WorkflowStep.next_attempt_at, WorkflowStep.id)
                    .limit(limit)
                )
            )

    def recover_intake(self, limit=100):
        """Recover abandoned evaluation deliveries without changing their effect identity."""
        with self.sessions() as session:
            steps = list(
                session.scalars(
                    select(WorkflowStep)
                    .join(
                        IntakeEvaluation,
                        WorkflowStep.data["evaluation_id"].as_string()
                        == cast(IntakeEvaluation.id, String),
                    )
                    .join(OutboxEvent, OutboxEvent.aggregate_id == IntakeEvaluation.id)
                    .where(
                        WorkflowStep.kind == "eligibility",
                        WorkflowStep.status == "completed",
                        WorkflowStep.data["evaluation_id"].as_string().is_not(None),
                        IntakeEvaluation.status == "pending",
                        OutboxEvent.event_type == "intake.evaluation_requested.v1",
                        OutboxEvent.published_at <= self.clock() - timedelta(seconds=75),
                    )
                    .limit(limit)
                )
            )
        for initial in steps:
            with self.sessions.begin() as session:
                # Match the intake worker's evaluation -> donation lock order.
                evaluation = session.get(
                    IntakeEvaluation, UUID(initial.data["evaluation_id"]), with_for_update=True
                )
                if evaluation is None or evaluation.status != "pending":
                    continue
                donation = session.scalar(
                    select(Donation)
                    .where(Donation.id == initial.donation_id)
                    .with_for_update(skip_locked=True)
                )
                if (
                    donation is None
                    or donation.version != initial.input_version
                    or donation.status != "matching"
                ):
                    continue
                row = session.get(WorkflowStep, initial.id, with_for_update=True)
                request_event = session.scalar(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.aggregate_id == evaluation.id,
                        OutboxEvent.event_type == "intake.evaluation_requested.v1",
                    )
                    .with_for_update()
                )
                now = self.clock()
                if (
                    request_event is None
                    or request_event.published_at is None
                    or request_event.published_at > now - timedelta(seconds=75)
                ):
                    continue
                if row.data.get("intake_retries", 0) >= 2:
                    evaluation.status, evaluation.failure_code = (
                        "failed",
                        "intake_delivery_exhausted",
                    )
                    self.fail(session, row, "intake_delivery_exhausted", now)
                    transition(
                        session, donation, "failed", "intake_delivery_exhausted", now, row.id
                    )
                else:
                    row.data = {**row.data, "intake_retries": row.data.get("intake_retries", 0) + 1}
                    request_event.published_at, request_event.lease_until = None, None
