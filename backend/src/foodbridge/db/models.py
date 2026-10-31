"""Intake-owned persistence plus the minimal shared identity/outbox foundation."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from foodbridge.db.base import Base


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(500))
    timezone: Mapped[str] = mapped_column(String(100))
    location = mapped_column(Geography("POINT", srid=4326, spatial_index=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    oidc_subject: Mapped[str] = mapped_column(String(500), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Base):
    __tablename__ = "memberships"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(30), primary_key=True)


class DonationDraft(Base):
    __tablename__ = "donation_drafts"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("status IN ('review_required','confirmed')", name="draft_status"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    donor_organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    pickup_location: Mapped[dict] = mapped_column(JSONB)
    extraction: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), default="review_required")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Donation(Base):
    __tablename__ = "donations"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("quantity_kg > 0", name="quantity_positive"),
        CheckConstraint(
            "pickup_end > pickup_start AND safe_use_by >= pickup_end", name="time_order"
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    draft_id: Mapped[UUID] = mapped_column(ForeignKey("donation_drafts.id"), unique=True)
    donor_organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    confirmed_data: Mapped[dict] = mapped_column(JSONB)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    pickup_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pickup_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    safe_use_by: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="submitted")
    version: Mapped[int] = mapped_column(Integer, default=1)
    matching_round: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class StatusHistory(Base):
    __tablename__ = "status_history"
    __table_args__ = (UniqueConstraint("donation_id", "aggregate_version"),)
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    donation_id: Mapped[UUID] = mapped_column(ForeignKey("donations.id"))
    aggregate_version: Mapped[int] = mapped_column(Integer)
    previous_status: Mapped[str | None] = mapped_column(String(30))
    next_status: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[UUID] = mapped_column(PGUUID)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (UniqueConstraint("aggregate_id", "aggregate_version", "event_type"),)
    event_id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID, index=True)
    aggregate_version: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(100))
    envelope: Mapped[dict] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    action: Mapped[str] = mapped_column(String(100), primary_key=True)
    key: Mapped[UUID] = mapped_column(PGUUID, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IntakeEvaluation(Base):
    __tablename__ = "intake_evaluations"
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    donor_organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    donation_id: Mapped[UUID] = mapped_column(ForeignKey("donations.id"))
    batch: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
