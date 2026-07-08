"""ORM models — one row per state-machine instance.

State columns hold the exact state names from app.state_machines;
services must check can_transition() before any state write (the
DB stores state, it does not enforce transitions). All money is
integer cents, never float.

DRAFT FOR REVIEW: table grain and columns are a first pass; the
state semantics come from state_machines.md.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


class Base(DeclarativeBase):
    # Timestamps feed the expiry-bounded backstop comparison; a
    # naive column under server-tz/DST skew is exactly the
    # "capture fires after the hold died" failure decisions.md
    # (2026-05-28) exists to prevent. Store tz-aware, always.
    type_annotation_map = {datetime: DateTime(timezone=True)}


class Planner(Base):
    __tablename__ = "planners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32), unique=True)
    # Stripe Connect (Standard) account that receives funds and is
    # merchant of record (on_behalf_of)
    stripe_account_id: Mapped[str] = mapped_column(String(64))


class Attendee(Base):
    __tablename__ = "attendees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32), unique=True)
    # Card on file lives on the PLATFORM account — a Stripe
    # constraint for destination charges (see skeleton_02)
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(64)
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    planner_id: Mapped[int] = mapped_column(
        ForeignKey("planners.id")
    )
    title: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime]
    # Fixed total the group splits (court rental), integer cents
    total_cost_cents: Mapped[int] = mapped_column(BigInteger)
    # Worst-case per-person share authorized at RSVP, integer cents
    worst_case_share_cents: Mapped[int] = mapped_column(BigInteger)
    # Event machine: draft/open/closed/settled/archived/cancelled
    state: Mapped[str] = mapped_column(
        String(16), default="draft"
    )
    # Planner's settle target choice; the EFFECTIVE backstop is
    # min(this, earliest auth expiry) — decisions.md 2026-05-28
    settle_target_at: Mapped[datetime | None]
    settle_default: Mapped[str] = mapped_column(
        String(24), default="assume_all_attended"
    )
    # Anchors the automatic settled → archived transition (72h)
    # and the post-settle edit window
    settled_at: Mapped[datetime | None]


class Rsvp(Base):
    __tablename__ = "rsvps"
    # One RSVP state-machine instance per attendee per event
    __table_args__ = (
        UniqueConstraint("event_id", "attendee_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    attendee_id: Mapped[int] = mapped_column(
        ForeignKey("attendees.id")
    )
    # RSVP machine: pending/going/going_paid/maybe/declined/
    # attended/no_show
    state: Mapped[str] = mapped_column(
        String(16), default="pending"
    )
    # Attendance machine: unconfirmed/present/absent — same grain
    # (per attendee per event), so it lives on the RSVP row
    attendance: Mapped[str] = mapped_column(
        String(16), default="unconfirmed"
    )


class Payment(Base):
    __tablename__ = "payments"
    # Terminal rows (voided, abandoned) stay for audit; an
    # attendee re-added after a void gets a NEW row with the next
    # attempt number — never a reused key against a dead intent
    __table_args__ = (
        UniqueConstraint("event_id", "attendee_id", "attempt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    attendee_id: Mapped[int] = mapped_column(
        ForeignKey("attendees.id")
    )
    attempt: Mapped[int] = mapped_column(default=1)
    # Payment machine: none/authorized/captured/voided/refunded/
    # failed/resolved/abandoned
    state: Mapped[str] = mapped_column(String(16), default="none")
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(64), unique=True
    )
    authorized_cents: Mapped[int | None] = mapped_column(BigInteger)
    captured_cents: Mapped[int | None] = mapped_column(BigInteger)
    # Extended Authorization is deferred: holds die 7 days after
    # creation. Every settle path must be bounded by this moment.
    auth_expires_at: Mapped[datetime | None]
    # Why the terminal state was reached (no_show, removed,
    # event_cancelled, auth_expired, ...) — for support questions
    state_reason: Mapped[str | None] = mapped_column(Text)
