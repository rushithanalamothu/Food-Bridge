"""Real PostgreSQL transactions: authenticated owner scope, retries, race and broker recovery."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import make_url

from foodbridge.agents.intake.demo import demo_batch
from foodbridge.agents.intake.relay import dispatch_pending
from foodbridge.agents.intake.service import IntakeService
from foodbridge.api.main import create_app
from foodbridge.auth.identity import current_donor
from foodbridge.db.models import (
    Donation,
    DonationDraft,
    IdempotencyRecord,
    IntakeEvaluation,
    Membership,
    Organization,
    OutboxEvent,
    StatusHistory,
    User,
)
from foodbridge.db.session import engine_for, session_factory
from foodbridge.domain.contracts import Location
from foodbridge.domain.errors import AppError
from foodbridge.domain.intake import DonationSubmit
from foodbridge.settings import Settings

NOW = datetime(2026, 10, 30, 22, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FOODBRIDGE_RUN_INTEGRATION") != "1",
        reason="Run make integration with services up",
    ),
]


@pytest.fixture(scope="session")
def isolated_database():
    # A throwaway database keeps the running local relay/worker out of transaction tests.
    settings = Settings()
    base_url = make_url(settings.database_url)
    name = "foodbridge_intake_test_" + uuid4().hex[:12]
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    test_url = base_url.set(database=name).render_as_string(hide_password=False)
    patch = pytest.MonkeyPatch()
    patch.setenv("FOODBRIDGE_DATABASE_URL", test_url)
    try:
        config = Config("backend/alembic.ini")
        command.upgrade(config, "head")
        # Verify only the new tables round-trip in this empty throwaway database.
        command.downgrade(config, "0001")
        command.upgrade(config, "head")
        yield test_url
    finally:
        engine_for(test_url).dispose()
        patch.undo()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture
def workspace(isolated_database):
    from foodbridge.domain.intake import DonorIdentity

    settings = Settings(enable_local_intake_demo=True)
    sessions = session_factory(settings.database_url)
    org_id, user_id = uuid4(), uuid4()
    location = Location(address="Synthetic test kitchen", latitude=37.332, longitude=-121.89)
    with sessions.begin() as session:
        session.add(
            Organization(
                id=org_id,
                name="Test Kitchen",
                address=location.address,
                timezone=location.timezone,
                location="SRID=4326;POINT(-121.89 37.332)",
                active=True,
            )
        )
        session.add(
            User(id=user_id, oidc_subject=f"test:{user_id}", display_name="Test donor", active=True)
        )
        session.flush()
        session.add(Membership(user_id=user_id, organization_id=org_id, role="donor"))
    actor = DonorIdentity(
        user_id=user_id,
        organization_id=org_id,
        organization_name="Test Kitchen",
        display_name="Test donor",
        pickup_location=location,
        mode="local_demo",
    )
    app = create_app(settings)
    app.state.clock = lambda: NOW
    app.dependency_overrides[current_donor] = lambda: actor
    yield (
        TestClient(app),
        actor,
        IntakeService(settings.database_url, lambda: NOW, allow_synthetic=True),
        settings,
    )
    with sessions.begin() as session:
        donation_ids = select(Donation.id).where(Donation.donor_organization_id == org_id)
        evaluation_ids = select(IntakeEvaluation.id).where(
            IntakeEvaluation.donor_organization_id == org_id
        )
        session.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(evaluation_ids)))
        session.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(donation_ids)))
        session.execute(delete(StatusHistory).where(StatusHistory.donation_id.in_(donation_ids)))
        session.execute(
            delete(IntakeEvaluation).where(IntakeEvaluation.donor_organization_id == org_id)
        )
        session.execute(delete(Donation).where(Donation.donor_organization_id == org_id))
        session.execute(delete(DonationDraft).where(DonationDraft.donor_organization_id == org_id))
        session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.actor_id == user_id))
        session.execute(delete(Membership).where(Membership.user_id == user_id))
        session.execute(delete(User).where(User.id == user_id))
        session.execute(delete(Organization).where(Organization.id == org_id))


def create_request(client, actor):
    example = json.loads((ROOT / "contracts/examples/donation-input.json").read_text())
    description = (
        "Food: vegetable rice meals. 20 meals, 10 kg. Refrigerated. Vegetarian. Allergens: soy. "
        "Today pickup 4 PM to 6 PM. Use by 8 PM."
    )
    result = client.post(
        "/api/v1/donation-drafts",
        headers={"Idempotency-Key": str(uuid4())},
        json={"description": description, "pickup_location": actor.pickup_location.model_dump()},
    )
    assert result.status_code == 201, result.text
    draft = result.json()
    example.update(description=description, pickup_location=actor.pickup_location.model_dump())
    return {
        "draft_id": draft["id"],
        "expected_draft_version": draft["version"],
        "confirmed": True,
        "donation": example,
    }


def test_http_description_to_post_is_durable_idempotent_and_scoped(workspace):
    client, actor, service, settings = workspace
    body = create_request(client, actor)
    key = {"Idempotency-Key": str(uuid4())}
    first = client.post("/api/v1/donations", headers=key, json=body)
    assert first.status_code == 202, first.text
    assert client.post("/api/v1/donations", headers=key, json=body).json() == first.json()
    identifier = first.json()["donation"]["id"]
    assert client.get(f"/api/v1/donations/{identifier}").status_code == 200
    assert client.get(f"/api/v1/donation-drafts/{body['draft_id']}").json()["status"] == "confirmed"
    assert client.get("/api/v1/donations").json()["items"][0]["donation"]["id"] == identifier
    with service.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Donation)
                .where(Donation.donor_organization_id == actor.organization_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(StatusHistory)
                .where(StatusHistory.donation_id == identifier)
            )
            == 1
        )
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == identifier))
        assert event.event_type == "donation.submitted.v1"
        assert event.published_at is None
        assert "Synthetic test kitchen" not in json.dumps(event.envelope)
        assert "vegetable rice" not in json.dumps(event.envelope)
    body["donation"]["quantity_kg"] = 11
    assert client.post("/api/v1/donations", headers=key, json=body).status_code == 409
    other = actor.model_copy(update={"organization_id": uuid4()})
    with pytest.raises(AppError) as error:
        service.get_donation(other, identifier)
    assert error.value.status == 404
    assert client.get("/api/v1/donations?cursor=garbage").status_code == 400


def test_unconfirmed_expired_and_stale_drafts_cannot_be_posted(workspace):
    client, actor, service, _settings = workspace
    body = create_request(client, actor)
    key = {"Idempotency-Key": str(uuid4())}
    body["confirmed"] = False
    assert client.post("/api/v1/donations", headers=key, json=body).status_code == 422
    body["confirmed"] = True
    body["expected_draft_version"] = 99
    assert client.post("/api/v1/donations", headers=key, json=body).status_code == 409
    body["expected_draft_version"] = 1
    body["donation"]["pickup_window"] = {
        "start": "2026-10-30T18:00:00Z",
        "end": "2026-10-30T19:00:00Z",
    }
    assert client.post("/api/v1/donations", headers=key, json=body).status_code == 422
    assert service.get_draft(actor, body["draft_id"]).status == "review_required"


def test_two_concurrent_posts_create_one_donation(workspace):
    client, actor, service, _settings = workspace
    body = DonationSubmit.model_validate(create_request(client, actor))

    def post(_):
        try:
            return service.submit(actor, body, uuid4(), uuid4())
        except AppError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(post, range(2)))
    assert sum(value == 409 for value in results) == 1
    assert len([value for value in results if value != 409]) == 1


def test_eligibility_outbox_recovers_and_duplicate_worker_delivery_has_one_effect(workspace):
    client, actor, service, settings = workspace
    body = create_request(client, actor)
    snapshot = service.submit(actor, DonationSubmit.model_validate(body), uuid4(), uuid4())
    batch = demo_batch(snapshot, NOW)
    job = service.request_evaluation(actor, batch, uuid4(), uuid4())

    def unavailable(_):
        raise OperationalError("test broker unavailable")

    dispatch_pending(settings, publish=unavailable, evaluation_id=job.id)
    assert service.get_evaluation(actor, job.id).status == "pending"
    with service.sessions.begin() as session:
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id))
        assert event.published_at is None
        event.lease_until = None
    published = []
    assert dispatch_pending(settings, publish=published.append, evaluation_id=job.id) >= 1
    assert str(job.id) in published
    first = service.process_evaluation(job.id)
    second = service.process_evaluation(job.id)
    assert first == second
    assert first.result.decisions[0].eligible
    assert "insufficient_capacity" in first.result.decisions[1].reasons
    with service.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.aggregate_id == job.id,
                    OutboxEvent.event_type == "intake.evaluated.v1",
                )
            )
            == 1
        )
    assert service.get_donation(actor, snapshot.donation.id).donation.status == "submitted"


def test_old_batch_cannot_overwrite_new_donation_state(workspace):
    client, actor, service, _settings = workspace
    snapshot = service.submit(
        actor, DonationSubmit.model_validate(create_request(client, actor)), uuid4(), uuid4()
    )
    job = service.request_evaluation(actor, demo_batch(snapshot, NOW), uuid4(), uuid4())
    with service.sessions.begin() as session:
        row = session.get(Donation, snapshot.donation.id)
        row.version += 1
    result = service.process_evaluation(job.id)
    assert result.status == "stale"
    assert result.result is None


def test_jwt_subject_resolves_server_membership_and_geometry(workspace, monkeypatch):
    from foodbridge.auth import identity

    client, actor, _service, _settings = workspace
    client.app.dependency_overrides.clear()
    monkeypatch.setattr(identity, "verified_subject", lambda *_: f"test:{actor.user_id}")
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer verified-by-unit-test"})
    assert response.status_code == 200, response.text
    assert response.json()["organization_id"] == str(actor.organization_id)
    assert response.json()["pickup_location"]["latitude"] == actor.pickup_location.latitude
    assert response.json()["mode"] == "oidc"


def test_packaging_is_preserved_and_draft_replay_does_not_call_model(workspace, monkeypatch):
    client, actor, service, _ = workspace
    from foodbridge.api.routes import intake as routes

    key = {"Idempotency-Key": str(uuid4())}
    body = {
        "description": "Food: rice meals. 20 boxed meals, 10 kg. Refrigerated. Allergens: none.",
        "pickup_location": actor.pickup_location.model_dump(),
    }
    first = client.post("/api/v1/donation-drafts", headers=key, json=body)
    assert first.status_code == 201
    assert first.json()["extraction"]["fields"]["packaging_type"] == "boxed"
    monkeypatch.setattr(routes, "extract", lambda *a, **k: pytest.fail("replay called provider"))
    assert client.post("/api/v1/donation-drafts", headers=key, json=body).json() == first.json()
    example = json.loads((ROOT / "contracts/examples/donation-input.json").read_text())
    example.update(description=body["description"], packaging_type="boxed")
    command_body = {
        "draft_id": first.json()["id"],
        "expected_draft_version": 1,
        "confirmed": True,
        "donation": example,
    }
    posted = client.post(
        "/api/v1/donations", headers={"Idempotency-Key": str(uuid4())}, json=command_body
    )
    assert posted.status_code == 202, posted.text
    assert (
        service.get_donation(actor, posted.json()["donation"]["id"]).donation.packaging_type
        == "boxed"
    )


def test_runtime_description_limit_blocks_before_extraction(workspace, monkeypatch):
    client, actor, _, _ = workspace
    from foodbridge.api.routes import intake as routes

    policy = client.get("/api/v1/intake/policy").json()
    assert policy["critical_window_s"] == 7200
    assert policy["high_window_s"] == 21600
    monkeypatch.setattr(
        routes, "extract", lambda *a, **k: pytest.fail("invalid text called provider")
    )
    result = client.post(
        "/api/v1/donation-drafts",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "description": "x" * (policy["max_description_length"] + 1),
            "pickup_location": actor.pickup_location.model_dump(),
        },
    )
    assert result.status_code == 400
    assert result.json()["code"] == "description_too_long"


def test_same_key_concurrent_submission_returns_identical_result(workspace):
    client, actor, service, _ = workspace
    body = DonationSubmit.model_validate(create_request(client, actor))
    key, correlation_id = uuid4(), uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: service.submit(actor, body, key, correlation_id), range(2))
        )
    assert results[0] == results[1]
    with service.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Donation)
                .where(Donation.donor_organization_id == actor.organization_id)
            )
            == 1
        )


def test_database_failure_rolls_back_donation_audit_and_outbox(workspace, monkeypatch):
    from sqlalchemy.exc import OperationalError as DatabaseError

    from foodbridge.agents.intake import service as module

    client, actor, service, _ = workspace
    body = create_request(client, actor)
    key = {"Idempotency-Key": str(uuid4())}
    original = module._event

    def unavailable(*args, **kwargs):
        raise DatabaseError("synthetic DB failure", {}, Exception("sensitive internal failure"))

    monkeypatch.setattr(module, "_event", unavailable)
    failed = client.post("/api/v1/donations", headers=key, json=body)
    assert failed.status_code == 503
    assert "sensitive internal failure" not in failed.text
    with service.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Donation)
                .where(Donation.donor_organization_id == actor.organization_id)
            )
            == 0
        )
        assert session.get(DonationDraft, body["draft_id"]).status == "review_required"
    monkeypatch.setattr(module, "_event", original)
    assert client.post("/api/v1/donations", headers=key, json=body).status_code == 202


def test_publication_retries_and_send_before_ack_crash_do_not_duplicate_effects(workspace):
    client, actor, service, settings = workspace
    snapshot = service.submit(
        actor, DonationSubmit.model_validate(create_request(client, actor)), uuid4(), uuid4()
    )
    batch = demo_batch(snapshot, NOW)
    job = service.request_evaluation(actor, batch, uuid4(), uuid4())

    def reset_lease():
        with service.sessions.begin() as session:
            row = session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id))
            assert row.published_at is None
            row.lease_until = None

    def unavailable(_):
        raise OperationalError("broker unavailable")

    for _ in range(3):
        dispatch_pending(settings, publish=unavailable, evaluation_id=job.id)
        reset_lease()
    published = []

    def send_then_crash(identifier):
        published.append(identifier)
        raise OSError("send succeeded but relay died before marking published")

    dispatch_pending(settings, publish=send_then_crash, evaluation_id=job.id)
    reset_lease()
    dispatch_pending(settings, publish=published.append, evaluation_id=job.id)
    assert published == [str(job.id), str(job.id)]
    assert service.process_evaluation(job.id) == service.process_evaluation(job.id)
    with service.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.aggregate_id == job.id,
                    OutboxEvent.event_type == "intake.evaluated.v1",
                )
            )
            == 1
        )


def test_internal_handoff_excludes_failed_candidates_and_rechecks_freshness(workspace):
    from datetime import timedelta

    client, actor, service, _ = workspace
    snapshot = service.submit(
        actor, DonationSubmit.model_validate(create_request(client, actor)), uuid4(), uuid4()
    )
    batch = demo_batch(snapshot, NOW)
    job = service.request_evaluation(actor, batch, uuid4(), uuid4())
    with pytest.raises(AppError, match="not complete"):
        service.get_handoff(job.id)
    service.process_evaluation(job.id)
    handoff = service.get_handoff(job.id)
    assert handoff.donation.id == snapshot.donation.id
    assert handoff.result.donation_decision == "eligible"
    assert [candidate.recipient.organization_id for candidate in handoff.eligible_candidates] == [
        batch.candidates[0].recipient.organization_id
    ]
    service.clock = lambda: NOW + timedelta(seconds=301)
    assert service.get_handoff(job.id).eligible_candidates == []
    service.clock = lambda: snapshot.donation.pickup_window.end
    with pytest.raises(AppError, match="new validation"):
        service.get_handoff(job.id)
    service.clock = lambda: NOW
    service.policy = service.policy.model_copy(update={"version": "changed-policy"})
    with pytest.raises(AppError, match="new eligibility"):
        service.get_handoff(job.id)


def test_pre_packaging_idempotency_receipt_still_replays(workspace):
    import hashlib

    client, actor, service, _ = workspace
    body = create_request(client, actor)
    key = uuid4()
    first = service.submit(actor, DonationSubmit.model_validate(body), key, uuid4())
    legacy_body = DonationSubmit.model_validate(body).model_dump(mode="json")
    legacy_body["donation"].pop("packaging_type", None)
    with service.sessions.begin() as session:
        receipt = session.get(IdempotencyRecord, (actor.user_id, "donations", key))
        receipt.request_hash = hashlib.sha256(
            json.dumps(legacy_body, sort_keys=True).encode()
        ).hexdigest()
    replay = service.submit(actor, DonationSubmit.model_validate(body), key, uuid4())
    assert replay.donation.id == first.donation.id
    body["donation"]["packaging_type"] = "boxed"
    with pytest.raises(AppError, match="different details"):
        service.submit(actor, DonationSubmit.model_validate(body), key, uuid4())
