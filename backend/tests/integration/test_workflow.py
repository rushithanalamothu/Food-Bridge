"""Workbook acceptance, concurrency, lease fencing and scoped replay on real PostgreSQL."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic import command as migration
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from foodbridge.agents.intake.service import IntakeService
from foodbridge.agents.orchestrator.demo import DemoMatching
from foodbridge.agents.orchestrator.relay import dispatch_pending
from foodbridge.agents.orchestrator.service import WorkflowService
from foodbridge.agents.reservation.notifications import SandboxNotifications, deliver_pending
from foodbridge.agents.reservation.service import ReservationService
from foodbridge.api.main import create_app
from foodbridge.api.stream import StreamService, publish_stream
from foodbridge.auth.identity import current_donor
from foodbridge.auth.workflow import current_actor
from foodbridge.db.base import Base
from foodbridge.db.models import (
    Donation,
    IntakeEvaluation,
    Membership,
    Organization,
    OutboxEvent,
    StatusHistory,
    User,
)
from foodbridge.db.session import engine_for, session_factory
from foodbridge.db.workflow_models import (
    Assignment,
    Capacity,
    Driver,
    Impact,
    MatchOffer,
    RecipientState,
    Reservation,
    TaskFailure,
    WorkflowStep,
)
from foodbridge.domain.contracts import (
    DonationInput,
    Location,
    PickupWindow,
    RecipientProfile,
    ReservationRequest,
)
from foodbridge.domain.errors import AppError
from foodbridge.domain.intake import DonationSubmit, DonorIdentity, DraftCreate, DriverFacts
from foodbridge.domain.workflow import (
    Actor,
    DeliveryConfirmation,
    DonationCommand,
    PickupConfirmation,
    VersionCommand,
)
from foodbridge.integrations.workflow import UnconfiguredMatching
from foodbridge.settings import Settings

NOW = datetime(2026, 10, 30, 22, tzinfo=UTC)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FOODBRIDGE_RUN_INTEGRATION") != "1",
        reason="Run make integration with services up",
    ),
]


@pytest.fixture(scope="module")
def workflow_database():
    base = make_url(Settings().database_url)
    name = "foodbridge_workflow_test_" + uuid4().hex[:12]
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    url = base.set(database=name).render_as_string(hide_password=False)
    patch = pytest.MonkeyPatch()
    patch.setenv("FOODBRIDGE_DATABASE_URL", url)
    try:
        config = Config("backend/alembic.ini")
        migration.upgrade(config, "head")
        migration.check(config)
        migration.downgrade(config, "36120ccc9d0d")
        migration.upgrade(config, "head")
        yield url
    finally:
        engine_for(url).dispose()
        patch.undo()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture
def env(workflow_database):
    sessions = session_factory(workflow_database)
    # Only this suite's uniquely named throwaway database is ever truncated.
    with sessions.begin() as session:
        session.execute(
            text(
                "TRUNCATE "
                + ",".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
                + " RESTART IDENTITY CASCADE"
            )
        )
    clock = SimpleNamespace(now=NOW)
    location = Location(address="Synthetic kitchen", latitude=37.332, longitude=-121.89)
    actors = {}
    drivers = []
    with sessions.begin() as session:
        for role in ("donor", "recipient", "recipient2", "driver", "driver2", "operator"):
            org_id, user_id = uuid4(), uuid4()
            if role == "operator":
                org_id = actors["donor"].organization_id
            else:
                session.add(
                    Organization(
                        id=org_id,
                        name=f"Synthetic {role}",
                        address=location.address,
                        timezone=location.timezone,
                        location="SRID=4326;POINT(-121.89 37.332)",
                        active=True,
                    )
                )
            session.add(
                User(
                    id=user_id,
                    oidc_subject=f"workflow-test:{user_id}",
                    display_name=role,
                    active=True,
                )
            )
            session.flush()
            actual_role = role.rstrip("2")
            session.add(Membership(user_id=user_id, organization_id=org_id, role=actual_role))
            actors[role] = Actor(user_id=user_id, organization_id=org_id, role=actual_role)
            if actual_role == "recipient":
                profile = RecipientProfile(
                    organization_id=org_id,
                    location=location,
                    accepted_categories=["prepared_meals"],
                    accepted_storage=["chilled"],
                    available_capacity_kg_by_storage={"chilled": 20},
                    rejected_allergens=["peanut"],
                    required_dietary_tags=["vegetarian"],
                    version=1,
                    receiving_window=PickupWindow(
                        start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=6)
                    ),
                )
                session.add(
                    RecipientState(
                        organization_id=org_id,
                        profile=profile.model_dump(mode="json"),
                        version=1,
                        verified=True,
                    )
                )
                session.add(
                    Capacity(organization_id=org_id, storage="chilled", reported_free_kg=20)
                )
            elif actual_role == "driver":
                identifier = uuid4()
                facts = DriverFacts(
                    id=identifier,
                    available=True,
                    capacity_kg=40,
                    storage_types=["chilled"],
                    to_pickup_time_s=0,
                    window=PickupWindow(
                        start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=6)
                    ),
                )
                session.add(
                    Driver(
                        id=identifier,
                        user_id=user_id,
                        organization_id=org_id,
                        facts=facts.model_dump(mode="json"),
                    )
                )
                drivers.append(identifier)
    donor = DonorIdentity(
        **actors["donor"].model_dump(exclude={"role"}),
        organization_name="Synthetic donor",
        display_name="Donor",
        pickup_location=location,
        mode="local_demo",
    )
    settings = Settings(
        database_url=workflow_database,
        enable_local_intake_demo=True,
        enable_local_workflow_demo=True,
        notification_mode="sandbox",
        ai_provider="rules",
    )

    def now():
        return clock.now

    app = create_app(settings)
    app.state.clock = now
    app.dependency_overrides[current_donor] = lambda: donor
    current = SimpleNamespace(actor=actors["recipient"])
    app.dependency_overrides[current_actor] = lambda: current.actor
    return SimpleNamespace(
        url=workflow_database,
        sessions=sessions,
        clock=clock,
        actors=actors,
        donor=donor,
        drivers=drivers,
        settings=settings,
        app=app,
        client=TestClient(app),
        current=current,
        intake=IntakeService(workflow_database, now, allow_synthetic=True),
        workflow=WorkflowService(workflow_database, now, allow_synthetic=True),
        reservation=ReservationService(workflow_database, now, allow_synthetic=True),
        gateway=DemoMatching(workflow_database, now),
    )


def submit(env, quantity=10):
    value = DonationInput(
        description="Synthetic vegetable rice, reviewed by donor",
        food_name="Rice",
        category="prepared_meals",
        quantity_kg=quantity,
        storage="chilled",
        dietary_tags=["vegetarian"],
        allergens=["soy"],
        pickup_location=env.donor.pickup_location,
        pickup_window=PickupWindow(start=NOW - timedelta(minutes=5), end=NOW + timedelta(hours=2)),
        safe_use_by=NOW + timedelta(hours=3),
    )
    draft_body = DraftCreate(description=value.description, pickup_location=value.pickup_location)
    from foodbridge.domain.intake import ExtractionResult, ProposedFields

    draft = env.intake.create_draft(
        env.donor,
        draft_body,
        ExtractionResult(
            fields=ProposedFields(),
            issues=[],
            provider="rules",
            model=None,
            prompt_version="test",
            request_id=uuid4(),
        ),
        uuid4(),
    )
    return env.intake.submit(
        env.donor,
        DonationSubmit(
            draft_id=draft.id, expected_draft_version=draft.version, confirmed=True, donation=value
        ),
        uuid4(),
        uuid4(),
    ).donation.id


def consume_all(env):
    with env.sessions() as session:
        ids = list(
            session.scalars(
                select(OutboxEvent.event_id).where(
                    OutboxEvent.event_type != "intake.evaluation_requested.v1"
                )
            )
        )
    for identifier in ids:
        env.workflow.consume(identifier)


def offer(env, identifier=None):
    identifier = identifier or submit(env)
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.donation_id == identifier,
                WorkflowStep.kind == "eligibility",
                WorkflowStep.status == "pending",
            )
        )
    env.workflow.run_step(step.id, env.gateway)
    with env.sessions() as session:
        evaluation = session.scalar(
            select(IntakeEvaluation)
            .where(
                IntakeEvaluation.donation_id == identifier,
                IntakeEvaluation.batch["expected_donation_version"].as_integer()
                == step.input_version,
            )
            .order_by(IntakeEvaluation.created_at.desc())
        )
    env.intake.process_evaluation(evaluation.id)
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.donation_id == identifier,
                WorkflowStep.kind == "matching",
                WorkflowStep.status == "pending",
            )
        )
    env.workflow.run_step(step.id, env.gateway)
    with env.sessions() as session:
        row = session.scalar(
            select(MatchOffer).where(
                MatchOffer.donation_id == identifier, MatchOffer.status == "offered"
            )
        )
        return row


def recipient_for(env, match):
    return next(
        a
        for a in env.actors.values()
        if a.role == "recipient" and a.organization_id == match.recipient_organization_id
    )


def reserve(env, match):
    with env.sessions() as session:
        version = session.get(Donation, match.donation_id).version
    return env.reservation.reserve(
        recipient_for(env, match),
        ReservationRequest(match_id=match.id, expected_donation_version=version),
        uuid4(),
        uuid4(),
    )


def assign(env, match):
    reserve(env, match)
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.donation_id == match.donation_id,
                WorkflowStep.kind == "assignment",
                WorkflowStep.status == "pending",
            )
        )
    env.workflow.run_step(step.id, env.gateway)
    with env.sessions() as session:
        return session.scalar(
            select(Assignment).where(
                Assignment.donation_id == match.donation_id, Assignment.status == "assigned"
            )
        )


def driver_for(env, assignment):
    with env.sessions() as session:
        driver = session.get(Driver, assignment.driver_id)
    return next(a for a in env.actors.values() if a.user_id == driver.user_id)


def test_at1_at2_valid_offer_and_hard_filter(env):
    with env.sessions.begin() as session:
        row = session.get(RecipientState, env.actors["recipient2"].organization_id)
        row.profile = {**row.profile, "rejected_allergens": ["soy"]}
    match = offer(env)
    assert match.recipient_organization_id == env.actors["recipient"].organization_id
    assert "SYNTHETIC" in match.recommendation["explanation"]
    with env.sessions() as session:
        result = session.get(IntakeEvaluation, match.evaluation_id).result
        assert any("allergen_conflict" in d["reasons"] for d in result["decisions"])
        assert session.get(Donation, match.donation_id).status == "offered"


def test_at3_concurrent_accept_exactly_one_success(env):
    match = offer(env)

    def accept(_):
        try:
            return reserve(env, match)
        except AppError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept, range(2)))
    assert sum(isinstance(x, dict) for x in results) == 1
    assert 409 in results
    with env.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Reservation)) == 1
        cap = session.get(Capacity, (match.recipient_organization_id, "chilled"))
        assert cap.committed_inbound_kg == 10


def test_same_key_replays_original_response_and_changed_body_conflicts(env):
    match = offer(env)
    actor = recipient_for(env, match)
    body = ReservationRequest(
        match_id=match.id, expected_donation_version=match.recommendation["donation_version"]
    )
    key = uuid4()
    first = env.reservation.reserve(actor, body, key, uuid4())
    assert env.reservation.reserve(actor, body, key, uuid4()) == first
    with pytest.raises(AppError, match="different details"):
        env.reservation.reserve(
            actor, body.model_copy(update={"expected_donation_version": 999}), key, uuid4()
        )


def test_two_donations_compete_for_recipient_capacity(env):
    # Both precomputed offers fit; the second acceptance must recheck current capacity.
    with env.sessions.begin() as session:
        session.get(RecipientState, env.actors["recipient2"].organization_id).verified = False
        session.get(
            Capacity, (env.actors["recipient"].organization_id, "chilled")
        ).reported_free_kg = 15
    first, second = offer(env), offer(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, env, match) for match in (first, second)]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except AppError as exc:
                results.append(exc.status)
    assert sum(isinstance(x, dict) for x in results) == 1
    assert 409 in results
    with env.sessions() as session:
        cap = session.get(Capacity, (env.actors["recipient"].organization_id, "chilled"))
        assert cap.committed_inbound_kg == 10 and cap.reported_free_kg == 15


def test_at4_decline_rematches_other_recipient(env):
    first = offer(env)
    env.reservation.decline(
        recipient_for(env, first), first.id, VersionCommand(expected_version=1), uuid4(), uuid4()
    )
    second = offer(env, first.donation_id)
    assert first.recipient_organization_id != second.recipient_organization_id
    assert second.matching_round == 2


def test_at5_duplicate_delivery_and_publish_crash_are_recoverable(env):
    identifier = submit(env)

    def sent_then_crashed(event_id):
        env.workflow.consume(UUID(event_id))
        raise OSError("crash after send")

    assert (
        dispatch_pending(env.settings, publish=sent_then_crashed, clock=lambda: env.clock.now) == 0
    )
    env.clock.now += timedelta(seconds=31)
    dispatch_pending(
        env.settings,
        publish=lambda value: env.workflow.consume(UUID(value)),
        clock=lambda: env.clock.now,
    )
    consume_all(env)
    with env.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowStep)
                .where(WorkflowStep.donation_id == identifier)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(StatusHistory)
                .where(StatusHistory.donation_id == identifier)
            )
            == 2
        )


def test_worker_lease_fences_old_results(env):
    identifier = submit(env)
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(select(WorkflowStep).where(WorkflowStep.donation_id == identifier))
    old, donation, _, _ = env.workflow.claim(step.id)
    env.clock.now += timedelta(seconds=76)
    fresh, donation, _, _ = env.workflow.claim(step.id)
    batch = env.gateway.candidates(donation, set(), set())
    env.workflow.finish(old, batch)
    with env.sessions() as session:
        assert session.scalar(select(func.count()).select_from(IntakeEvaluation)) == 0
    env.workflow.finish(fresh, batch)
    env.workflow.finish(fresh, batch)
    with env.sessions() as session:
        assert session.scalar(select(func.count()).select_from(IntakeEvaluation)) == 1


def test_at6_unavailable_provider_exhausts_into_audited_replay(env):
    identifier = submit(env)
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(select(WorkflowStep).where(WorkflowStep.donation_id == identifier))
    for _ in range(3):
        env.workflow.run_step(step.id, UnconfiguredMatching())
        env.clock.now += timedelta(seconds=35)
    with env.sessions() as session:
        failure = session.scalar(select(TaskFailure))
        donation = session.get(Donation, identifier)
        assert failure.attempts == 3
        assert session.scalar(select(func.count()).select_from(MatchOffer)) == 0
    env.workflow.replay(
        env.actors["operator"],
        failure.id,
        VersionCommand(expected_version=donation.version),
        uuid4(),
    )
    env.workflow.run_step(step.id, env.gateway)
    with env.sessions() as session:
        assert session.get(WorkflowStep, step.id).attempts == 4
        assert session.get(TaskFailure, failure.id).replay_count == 1


def test_at7_no_candidate_and_deadline_never_force_match(env):
    with env.sessions.begin() as session:
        for row in session.scalars(select(RecipientState)):
            row.verified = False
    identifier = submit(env)
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(select(WorkflowStep).where(WorkflowStep.donation_id == identifier))
    env.workflow.run_step(step.id, env.gateway)
    with env.sessions() as session:
        evaluation = session.scalar(select(IntakeEvaluation))
    env.intake.process_evaluation(evaluation.id)
    consume_all(env)
    with env.sessions() as session:
        match_step = session.scalar(select(WorkflowStep).where(WorkflowStep.kind == "matching"))
    env.workflow.run_step(match_step.id, env.gateway)
    with env.sessions() as session:
        assert session.get(Donation, identifier).status == "no_match"
    another = submit(env)
    env.clock.now += timedelta(hours=3)
    env.workflow.sweep()
    with env.sessions() as session:
        assert session.get(Donation, another).status == "expired"
        assert session.scalar(select(func.count()).select_from(MatchOffer)) == 0


def test_full_reservation_pickup_delivery_and_impact_exactly_once(env):
    match = offer(env)
    assignment = assign(env, match)
    actor = driver_for(env, assignment)
    accepted = env.reservation.pickup_command(
        actor, assignment.id, "accept", VersionCommand(expected_version=1), uuid4(), uuid4()
    )
    picked = env.reservation.pickup_command(
        actor,
        assignment.id,
        "confirm-pickup",
        PickupConfirmation(
            expected_version=accepted["version"], handling_confirmed=True, observed_quantity_kg=10
        ),
        uuid4(),
        uuid4(),
    )
    body = DeliveryConfirmation(expected_version=picked["version"], delivery_confirmed=True)
    key = uuid4()
    delivered = env.reservation.pickup_command(
        actor, assignment.id, "confirm-delivery", body, key, uuid4()
    )
    assert delivered["donation"]["status"] == "delivered"
    assert (
        env.reservation.pickup_command(actor, assignment.id, "confirm-delivery", body, key, uuid4())
        == delivered
    )
    with env.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Impact)) == 1
        cap = session.get(Capacity, (match.recipient_organization_id, "chilled"))
        assert cap.reported_free_kg == 10 and cap.committed_inbound_kg == 0
    consume_all(env)
    assert deliver_pending(env.url, SandboxNotifications(), clock=lambda: env.clock.now) > 0
    assert deliver_pending(env.url, SandboxNotifications(), clock=lambda: env.clock.now) == 0


def test_driver_decline_keeps_recipient_and_reassigns(env):
    match = offer(env)
    assignment = assign(env, match)
    actor = driver_for(env, assignment)
    env.reservation.pickup_command(
        actor, assignment.id, "decline", VersionCommand(expected_version=1), uuid4(), uuid4()
    )
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.kind == "assignment", WorkflowStep.status == "pending"
            )
        )
    env.workflow.run_step(step.id, env.gateway)
    with env.sessions() as session:
        active = session.scalar(select(Assignment).where(Assignment.status == "assigned"))
        assert active.driver_id != assignment.driver_id
        assert session.scalar(select(Reservation)).status == "active"
        assert (
            session.get(Capacity, (match.recipient_organization_id, "chilled")).committed_inbound_kg
            == 10
        )


def test_cancel_vs_pickup_race_leaves_consistent_allocation(env):
    match = offer(env)
    assignment = assign(env, match)
    actor = driver_for(env, assignment)
    accepted = env.reservation.pickup_command(
        actor, assignment.id, "accept", VersionCommand(expected_version=1), uuid4(), uuid4()
    )
    with env.sessions() as session:
        version = session.get(Donation, match.donation_id).version

    def cancel():
        return env.reservation.cancel(
            env.actors["donor"],
            match.donation_id,
            DonationCommand(expected_donation_version=version),
            uuid4(),
            uuid4(),
        )

    def pickup():
        return env.reservation.pickup_command(
            actor,
            assignment.id,
            "confirm-pickup",
            PickupConfirmation(
                expected_version=accepted["version"],
                handling_confirmed=True,
                observed_quantity_kg=10,
            ),
            uuid4(),
            uuid4(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(cancel), pool.submit(pickup)]
        outcomes = []
        for job in jobs:
            try:
                outcomes.append(job.result())
            except AppError as exc:
                outcomes.append(exc.status)
    assert 409 in outcomes
    with env.sessions() as session:
        donation = session.get(Donation, match.donation_id)
        cap = session.get(Capacity, (match.recipient_organization_id, "chilled"))
        assert (donation.status, cap.committed_inbound_kg) in {
            ("cancelled", Decimal(0)),
            ("picked_up", Decimal(10)),
        }


def test_scoped_http_errors_and_stream_replay(env):
    match = offer(env)
    actor = recipient_for(env, match)
    env.current.actor = actor
    assert env.client.get(f"/api/v1/matches/{match.id}").status_code == 200
    env.current.actor = (
        env.actors["recipient2"] if actor == env.actors["recipient"] else env.actors["recipient"]
    )
    assert env.client.get(f"/api/v1/matches/{match.id}").status_code == 404
    assert env.client.get("/api/v1/operations/failures").status_code == 403
    assert publish_stream(env.url, clock=lambda: env.clock.now) > 0
    assert publish_stream(env.url, clock=lambda: env.clock.now) == 0
    stream = StreamService(env.url, clock=lambda: env.clock.now)
    rows = stream.read(actor, 0)
    assert rows and len({row["sequence"] for row in rows}) == len(rows)
    outsider = Actor(user_id=uuid4(), organization_id=uuid4(), role="recipient")
    assert stream.read(outsider, 0) == []
    assert stream.read(actor, rows[-1]["sequence"]) == []
    env.clock.now += timedelta(days=8)
    assert stream.prune() > 0
    with pytest.raises(AppError) as exc:
        stream.cursor("0")
    assert exc.value.code == "stream_cursor_expired"


def test_stale_matching_result_cannot_reopen_cancelled_donation(env):
    identifier = submit(env)
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(select(WorkflowStep))
    claimed, donation, _, _ = env.workflow.claim(step.id)
    batch = env.gateway.candidates(donation, set(), set())
    env.reservation.cancel(
        env.actors["donor"],
        identifier,
        DonationCommand(expected_donation_version=donation.version),
        uuid4(),
        uuid4(),
    )
    env.workflow.finish(claimed, batch)
    with env.sessions() as session:
        assert session.get(Donation, identifier).status == "cancelled"
        assert session.get(WorkflowStep, step.id).status == "stale"
        assert session.scalar(select(func.count()).select_from(IntakeEvaluation)) == 0


def test_expired_route_triggers_fresh_eligibility_round(env):
    identifier = submit(env)
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(select(WorkflowStep).where(WorkflowStep.kind == "eligibility"))
    env.workflow.run_step(step.id, env.gateway)
    with env.sessions() as session:
        evaluation = session.scalar(select(IntakeEvaluation))
    env.intake.process_evaluation(evaluation.id)
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(select(WorkflowStep).where(WorkflowStep.kind == "matching"))
    env.clock.now += timedelta(minutes=20)
    env.workflow.run_step(step.id, env.gateway)
    with env.sessions() as session:
        donation = session.get(Donation, identifier)
        assert donation.status == "matching" and donation.matching_round == 2
        assert session.get(WorkflowStep, step.id).status == "stale"


def test_abandoned_intake_delivery_is_republished_with_same_id(env):
    submit(env)
    consume_all(env)
    with env.sessions() as session:
        step = session.scalar(select(WorkflowStep).where(WorkflowStep.kind == "eligibility"))
    env.workflow.run_step(step.id, env.gateway)
    with env.sessions.begin() as session:
        row = session.scalar(
            select(OutboxEvent).where(OutboxEvent.event_type == "intake.evaluation_requested.v1")
        )
        row.published_at = env.clock.now
        original = row.event_id
    env.clock.now += timedelta(seconds=76)
    env.workflow.recover_intake()
    with env.sessions() as session:
        assert session.get(OutboxEvent, original).published_at is None
        assert session.scalar(select(func.count()).select_from(IntakeEvaluation)) == 1


def test_unconsumed_acknowledged_broker_event_is_republished(env):
    identifier = submit(env)
    published = []
    dispatch_pending(env.settings, publish=published.append, clock=lambda: env.clock.now)
    env.clock.now += timedelta(seconds=76)
    dispatch_pending(env.settings, publish=published.append, clock=lambda: env.clock.now)
    assert len(published) == 2 and published[0] == published[1]
    env.workflow.consume(UUID(published[-1]))
    with env.sessions() as session:
        assert session.get(Donation, identifier).status == "matching"


def test_driver_commitment_race_uses_one_driver_lock(env):
    first, second = offer(env), offer(env)
    reserve(env, first)
    reserve(env, second)

    def allocate(match):
        with env.sessions.begin() as session:
            from foodbridge.db.workflow import locked_donation

            donation = locked_donation(session, match.donation_id)
            from foodbridge.domain.intake import EligibilityCandidate

            candidate = EligibilityCandidate.model_validate(match.candidate)
            candidate.driver = DriverFacts.model_validate(first.candidate["driver"])
            return env.reservation.assign(
                session,
                donation,
                session.get(MatchOffer, match.id),
                candidate,
                env.clock.now,
                uuid4(),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(allocate, match) for match in (first, second)]
        results = []
        for job in jobs:
            try:
                results.append(job.result())
            except AppError as exc:
                results.append(exc.code)
    assert "driver_busy" in results
    with env.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Assignment)) == 1


def test_accept_vs_offer_expiry_race_never_leaves_double_allocation(env):
    match = offer(env)
    with env.sessions.begin() as session:
        session.get(MatchOffer, match.id).expires_at = env.clock.now
    with ThreadPoolExecutor(max_workers=2) as pool:
        accept_job = pool.submit(reserve, env, match)
        sweep_job = pool.submit(env.workflow.sweep)
        with pytest.raises(AppError):
            accept_job.result()
        sweep_job.result()
    with env.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Reservation)) == 0
        assert (
            session.get(Capacity, (match.recipient_organization_id, "chilled")).committed_inbound_kg
            == 0
        )


def test_stream_cursor_order_follows_publication_of_committed_rows(env):
    from foodbridge.agents.intake.service import _event

    target = [{"organization_id": str(env.actors["donor"].organization_id), "role": "donor"}]
    session_a = env.sessions()
    try:
        event_a = _event(session_a, uuid4(), 1, "donation.updated.v1", env.clock.now, uuid4(), {})
        event_a.audience = target
        session_a.flush()  # Deliberately leave the earlier business transaction uncommitted.
        with env.sessions.begin() as session_b:
            event_b = _event(
                session_b, uuid4(), 1, "donation.updated.v1", env.clock.now, uuid4(), {}
            )
            event_b.audience = target
        assert publish_stream(env.url, clock=lambda: env.clock.now) == 1
        session_a.commit()
        assert publish_stream(env.url, clock=lambda: env.clock.now) == 1
        stream = StreamService(env.url)
        items = stream.read(env.actors["donor"], 0)
        assert [x["event"]["event_id"] for x in items] == [
            str(event_b.event_id),
            str(event_a.event_id),
        ]
    finally:
        session_a.close()


def test_client_role_selector_cannot_grant_another_membership(env, monkeypatch):
    env.app.dependency_overrides.pop(current_actor)
    with env.sessions() as session:
        subject = session.get(User, env.actors["donor"].user_id).oidc_subject
    monkeypatch.setattr("foodbridge.auth.workflow.verified_subject", lambda *_: subject)
    headers = {"Authorization": "Bearer test", "X-FoodBridge-Role": "recipient"}
    assert env.client.get("/api/v1/matches", headers=headers).status_code == 403
    headers["X-FoodBridge-Role"] = "donor"
    assert env.client.get("/api/v1/session", headers=headers).status_code == 200
    with env.sessions.begin() as session:
        session.get(User, env.actors["donor"].user_id).active = False
    assert env.client.get("/api/v1/session", headers=headers).status_code == 403
