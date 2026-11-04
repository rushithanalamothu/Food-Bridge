"""Additive workflow storage; recipient/match structures are the integration handoff."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from foodbridge.db.base import Base


class RecipientState(Base):
    __tablename__ = "recipient_profiles"
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    profile: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)


class Capacity(Base):
    __tablename__ = "recipient_capacity"
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    storage: Mapped[str] = mapped_column(String(30), primary_key=True)
    reported_free_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    committed_inbound_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint(
            "reported_free_kg >= committed_inbound_kg AND committed_inbound_kg >= 0",
            name="capacity_nonnegative",
        ),
        CheckConstraint("storage IN ('ambient','chilled','frozen')", name="storage"),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class Driver(Base):
    __tablename__ = "drivers"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    facts: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)


class MatchOffer(Base):
    __tablename__ = "matches"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    donation_id: Mapped[UUID] = mapped_column(ForeignKey("donations.id"), index=True)
    recipient_organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    evaluation_id: Mapped[UUID] = mapped_column(ForeignKey("intake_evaluations.id"))
    matching_round: Mapped[int] = mapped_column(Integer)
    recommendation: Mapped[dict] = mapped_column(JSONB)
    candidate: Mapped[dict] = mapped_column(JSONB)
    driver_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="offered")
    version: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('offered','accepted','declined','expired','superseded')", name="status"
        ),
        CheckConstraint("version >= 1 AND matching_round >= 1", name="versions_positive"),
        Index(
            "uq_matches_active_donation",
            "donation_id",
            unique=True,
            postgresql_where=text("status = 'offered'"),
        ),
    )


class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    donation_id: Mapped[UUID] = mapped_column(ForeignKey("donations.id"), index=True)
    match_id: Mapped[UUID] = mapped_column(ForeignKey("matches.id"))
    recipient_organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    storage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('active','released','completed','failed')", name="status"),
        CheckConstraint("quantity_kg > 0 AND version >= 1", name="quantity_version_positive"),
        Index(
            "uq_reservations_active_donation",
            "donation_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


class Assignment(Base):
    __tablename__ = "pickup_assignments"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    donation_id: Mapped[UUID] = mapped_column(ForeignKey("donations.id"), index=True)
    reservation_id: Mapped[UUID] = mapped_column(ForeignKey("reservations.id"))
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("drivers.id"), index=True)
    candidate: Mapped[dict] = mapped_column(JSONB)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="assigned")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('assigned','accepted','declined','collected',"
            "'delivered','released','failed')",
            name="status",
        ),
        CheckConstraint('"end" > start AND version >= 1', name="window_version"),
        Index(
            "uq_assignments_active_donation",
            "donation_id",
            unique=True,
            postgresql_where=text("status IN ('assigned','accepted','collected')"),
        ),
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    donation_id: Mapped[UUID] = mapped_column(ForeignKey("donations.id"), index=True)
    matching_round: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    input_version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        UniqueConstraint("donation_id", "matching_round", "kind", "input_version"),
        CheckConstraint(
            "status IN ('pending','running','completed','stale','failed')", name="status"
        ),
    )


class ConsumerReceipt(Base):
    __tablename__ = "consumer_receipts"
    consumer: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("outbox_events.event_id"), primary_key=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskFailure(Base):
    __tablename__ = "task_failures"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    step_id: Mapped[UUID] = mapped_column(ForeignKey("workflow_steps.id"), unique=True)
    donation_id: Mapped[UUID] = mapped_column(ForeignKey("donations.id"), index=True)
    code: Mapped[str] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    replay_count: Mapped[int] = mapped_column(Integer, default=0)
    replayed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("outbox_events.event_id"))
    donation_id: Mapped[UUID] = mapped_column(ForeignKey("donations.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    template: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID)
    provider_id: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)


class StreamEvent(Base):
    __tablename__ = "stream_events"
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("outbox_events.event_id"), unique=True)
    envelope: Mapped[dict] = mapped_column(JSONB)
    audience: Mapped[list] = mapped_column(JSONB)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Impact(Base):
    __tablename__ = "delivery_impact"
    donation_id: Mapped[UUID] = mapped_column(ForeignKey("donations.id"), primary_key=True)
    recipient_organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StreamState(Base):
    __tablename__ = "stream_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expired_through: Mapped[int] = mapped_column(BigInteger, default=0)
