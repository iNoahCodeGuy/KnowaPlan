"""ORM models — one row per state-machine instance.

State columns hold the exact state names from app.state_machines;
services must check can_transition() before any state write (the
DB stores state, it does not enforce transitions). All money is
integer cents, never float.

DRAFT FOR REVIEW: table grain and columns are a first pass; the
state semantics come from state_machines.md.
"""
import secrets
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


def _mint_token() -> str:
    # Capability-URL credential (decisions.md 2026-07-13): the link
    # IS the permission, so it must be unguessable — 128 bits from
    # the CSPRNG as 22 URL-safe chars. No collision-retry loop: the
    # column's unique index enforces what the birthday bound
    # (~1e-27 at a million rows) already promises; if the
    # impossible fires, the insert fails loudly.
    return secrets.token_urlsafe(16)


class Base(DeclarativeBase):
    # Store every timestamp tz-aware. Settle timing (settle_target_at,
    # settled_at, charge_requested_at) is compared across the wire and
    # audited; a naive column under server-tz/DST skew silently shifts
    # those moments. tz-aware, always.
    type_annotation_map = {datetime: DateTime(timezone=True)}


class Planner(Base):
    __tablename__ = "planners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32), unique=True)
    # Stripe Connect (Standard) account that receives funds and is
    # merchant of record (on_behalf_of)
    stripe_account_id: Mapped[str] = mapped_column(String(64))
    # The planner's own participation: a playing planner is an
    # ordinary Attendee + Rsvp row (decisions.md 2026-07-16). They
    # count in the split divisor when present but are NEVER charged
    # — no Payment row. None = not playing.
    attendee_id: Mapped[int | None] = mapped_column(
        ForeignKey("attendees.id")
    )


class Attendee(Base):
    __tablename__ = "attendees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32), unique=True)
    # Card on file lives on the PLATFORM account — a Stripe
    # constraint for destination charges (see skeleton_02). The card
    # is saved at RSVP via a SetupIntent (charge-at-close, no hold —
    # decisions.md 2026-07-15); None until the attendee saves one.
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(64)
    )
    # The saved PaymentMethod charged off-session at close. None =
    # cardless (gets a tap-to-pay link instead). Reusable across this
    # attendee's events once saved.
    stripe_payment_method_id: Mapped[str | None] = mapped_column(
        String(64)
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    planner_id: Mapped[int] = mapped_column(
        ForeignKey("planners.id")
    )
    # Capability URLs (decisions.md 2026-07-13): one token per
    # purpose, never reused across purposes — each route looks up
    # ONLY its own column, so a token can never authorize the
    # wrong purpose. /e/{event_token} = view + start an RSVP.
    event_token: Mapped[str] = mapped_column(
        String(32), unique=True, default=_mint_token
    )
    # /admin/{admin_token} = attendance, settlement, cancellation.
    # Whoever holds it IS the planner (accepted v0 risk).
    admin_token: Mapped[str] = mapped_column(
        String(32), unique=True, default=_mint_token
    )
    title: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime]
    # Fixed total the group splits (court rental), integer cents
    total_cost_cents: Mapped[int] = mapped_column(BigInteger)
    # Planner's expected headcount. Sizes NO hold (there is none) —
    # the RSVP estimate is total_cost_cents // goal_attendance
    # (charge-at-close, decisions.md 2026-07-15). The actual share at
    # close divides by who was marked present, not this.
    goal_attendance: Mapped[int]
    # The quoted estimate, snapshotted (decisions.md 2026-07-16):
    # total ÷ goal at creation, refreshable while draft, frozen once
    # open (enforced by the event-edit service, not the DB).
    # Cap-and-absorb caps at THIS, not a recomputed formula.
    estimated_share_cents: Mapped[int] = mapped_column(BigInteger)
    # Event machine: draft/open/closed/settled/archived/cancelled
    state: Mapped[str] = mapped_column(
        String(16), default="draft"
    )
    # Planner's settle target (end-of-day / +24h / +48h / +6d). No
    # auth expiry to bound it now — the backstop IS this target
    # (decisions.md 2026-07-15 supersedes the 2026-05-28 min()).
    settle_target_at: Mapped[datetime | None]
    # Auto-settle default: "assume_all_attended" (charge everyone
    # present) or "mark_all_absent" (charge nobody). Was "void_all".
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
    # /r/{rsvp_token}, minted at RSVP: lets this attendee change
    # THIS event's answer — per (event, attendee) like the row
    # itself, so a leaked or forwarded link touches one event only
    # (decisions.md 2026-07-16).
    rsvp_token: Mapped[str] = mapped_column(
        String(32), unique=True, default=_mint_token
    )
    # RSVP machine: pending/going/maybe/declined/attended/no_show.
    # A card on file is OPTIONAL and tracked on Payment/Attendee, not
    # here — no going_paid state (decisions.md 2026-07-15)
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
    # Terminal rows (refunded, abandoned) stay for audit; an attendee
    # re-added after abandoning gets a NEW row with the next attempt
    # number — never a reused idempotency key (decisions.md 2026-07-08)
    __table_args__ = (
        UniqueConstraint("event_id", "attendee_id", "attempt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    attendee_id: Mapped[int] = mapped_column(
        ForeignKey("attendees.id")
    )
    attempt: Mapped[int] = mapped_column(default=1)
    # Payment machine: none/paid/unpaid/refunded/abandoned
    # (charge-at-close, decisions.md 2026-07-15)
    state: Mapped[str] = mapped_column(String(16), default="none")
    # The LATEST charge attempt's PaymentIntent — the successful
    # off-session charge, a recorded decline, or the link's PI once
    # completed (decisions.md 2026-07-16). `state`, not this column,
    # says whether money was collected.
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(64), unique=True
    )
    # Cardless path: the Checkout Session behind the outstanding
    # tap-to-pay link. We poll its status on roster load to move
    # unpaid → paid — no webhook in v0 (decisions.md 2026-07-13,
    # 2026-07-15). None once paid by saved card, or never billed.
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(
        String(64), unique=True
    )
    # The actual share charged at close, integer cents. None until a
    # charge lands.
    charged_cents: Mapped[int | None] = mapped_column(BigInteger)
    # Record-first stamp: set in the same DB txn as the attendance
    # change, BEFORE the Stripe call; a row with this set but state
    # still `none` is a dangling charge, retried with the SAME
    # idempotency key (decisions.md 2026-07-13).
    charge_requested_at: Mapped[datetime | None]
    # Intent includes the amount (decisions.md 2026-07-16): Stripe
    # replays an idempotency key only for identical params, so a
    # dangling retry must re-send exactly what was stamped. Written
    # in the same txn as charge_requested_at.
    charge_requested_cents: Mapped[int | None] = mapped_column(
        BigInteger
    )
    # Why a terminal/unpaid state was reached (no_card, declined,
    # abandoned, ...) — for the roster and support questions
    state_reason: Mapped[str | None] = mapped_column(Text)
