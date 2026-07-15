"""Settlement — the record-first caller.

Owns the DB transactions AROUND app/payments.py (which owns the
Stripe calls): the settle-time state transitions and the intent
stamps commit BEFORE any money moves, so a crash leaves a queryable
dangling row, never an untraced charge (decisions.md 2026-07-13,
2026-07-16). Every state write goes through the tables in
app/state_machines.py — an illegal transition raises, never writes.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Payment, Planner, Rsvp
from app.payments import charge_share, create_payment_link
from app.state_machines import (
    ATTENDANCE,
    EVENT,
    PAYMENT,
    RSVP,
    can_transition,
)


@dataclass(frozen=True)
class Outcome:
    attendee_id: int
    result: str  # "paid" | "unpaid" | "dangling"
    link_url: str | None = None


@dataclass(frozen=True)
class SettlementReport:
    share_cents: int  # true split: floor(total ÷ present)
    charge_cents: int  # actually charged (< share if capped)
    shortfall_cents: int  # (share − charge) × charged attendees
    outcomes: tuple[Outcome, ...]


def _transition(
    machine: dict[str, set[str]],
    label: str,
    current: str,
    dst: str,
) -> str:
    """Check the table and return dst; an illegal transition is a
    bug and raises — never a silent write."""
    if not can_transition(machine, current, dst):
        raise ValueError(
            f"illegal {label} move {current!r} -> {dst!r}"
        )
    return dst


async def mark_attendance(
    session: AsyncSession, rsvp: Rsvp, present: bool
) -> Rsvp:
    """Planner marks one attendee: RSVP going -> attended|no_show
    and attendance unconfirmed -> present|absent, together in one
    commit — the two machines describe one fact and must never
    disagree in the DB. Both destinations are computed before
    either is assigned, so a half-legal pair cannot half-write."""
    rsvp_dst = "attended" if present else "no_show"
    att_dst = "present" if present else "absent"
    new_state = _transition(RSVP, "rsvp", rsvp.state, rsvp_dst)
    new_att = _transition(
        ATTENDANCE, "attendance", rsvp.attendance, att_dst
    )
    rsvp.state = new_state
    rsvp.attendance = new_att
    session.add(rsvp)
    await session.commit()
    return rsvp


async def close_rsvps(
    session: AsyncSession, event: Event
) -> Event:
    """Planner locks RSVPs: Event open -> closed. Manual close is
    the only close besides settlement beginning — settle_event
    invokes this too (state_machines.md)."""
    event.state = _transition(
        EVENT, "event", event.state, "closed"
    )
    session.add(event)
    await session.commit()
    return event


def _resolve_attendance(rsvp: Rsvp, present: bool) -> None:
    """Settle-time default for an undecided row — transitions only,
    no commit: the caller chooses the transaction it lands in."""
    rsvp_dst = "attended" if present else "no_show"
    att_dst = "present" if present else "absent"
    rsvp.state = _transition(RSVP, "rsvp", rsvp.state, rsvp_dst)
    rsvp.attendance = _transition(
        ATTENDANCE, "attendance", rsvp.attendance, att_dst
    )


async def settle_event(
    session: AsyncSession,
    event: Event,
    planner: Planner,
    *,
    cap_at_estimate: bool = False,
) -> SettlementReport:
    """Close -> split -> charge/link -> settled (decisions.md
    2026-07-16). The split divides by ALL participants including a
    playing planner; the planner's linked attendee is never charged.
    Record-first: each charged attendee's Payment row and both
    intent stamps (and their attendance resolution, if defaulted)
    land in ONE commit BEFORE any Stripe call. Zero participants is
    a valid settlement: charge nobody (scenarios.md). Absorbing
    (cap_at_estimate) is an active choice — the default charges the
    actual share, and any capped gap is reported, never silent."""
    if event.state == "open":
        await close_rsvps(session, event)
    if event.state != "closed":
        raise ValueError(
            f"cannot settle an event in state {event.state!r}"
        )
    rows = (
        await session.execute(
            select(Rsvp, Attendee)
            .join(Attendee, Rsvp.attendee_id == Attendee.id)
            .where(Rsvp.event_id == event.id)
        )
    ).all()
    assume = event.settle_default == "assume_all_attended"

    participants: list[tuple[Rsvp, Attendee]] = []
    defaulted_absent: list[Rsvp] = []
    for rsvp, attendee in rows:
        undecided = (
            rsvp.state == "going"
            and rsvp.attendance == "unconfirmed"
        )
        if rsvp.attendance == "present":
            participants.append((rsvp, attendee))
        elif undecided and assume:
            participants.append((rsvp, attendee))
        elif undecided:
            defaulted_absent.append(rsvp)

    # Defaulted absences move no money — one bulk commit.
    if defaulted_absent:
        for rsvp in defaulted_absent:
            _resolve_attendance(rsvp, present=False)
        await session.commit()

    divisor = len(participants)
    share = event.total_cost_cents // divisor if divisor else 0
    charge = share
    if cap_at_estimate:
        charge = min(share, event.estimated_share_cents)

    charged = [
        (rsvp, attendee)
        for rsvp, attendee in participants
        if attendee.id != planner.attendee_id
    ]
    outcomes: list[Outcome] = []
    for rsvp, attendee in charged:
        # Record-first: intent (row + when + how much) and any
        # defaulted attendance resolution are durable BEFORE the
        # money moves.
        if rsvp.attendance == "unconfirmed":
            _resolve_attendance(rsvp, present=True)
        payment = Payment(
            event_id=event.id,
            attendee_id=attendee.id,
            attempt=1,
            state="none",
            charge_requested_at=datetime.now(timezone.utc),
            charge_requested_cents=charge,
        )
        session.add(payment)
        await session.commit()

        if attendee.stripe_payment_method_id is not None:
            await charge_share(payment, attendee, planner, charge)
            await session.commit()
            outcomes.append(Outcome(attendee.id, payment.state))
        else:
            payment.state = _transition(
                PAYMENT, "payment", payment.state, "unpaid"
            )
            payment.state_reason = "no_card"
            await session.commit()
            url = await create_payment_link(
                payment, planner, charge
            )
            await session.commit()
            outcomes.append(
                Outcome(attendee.id, "unpaid", link_url=url)
            )

    # A playing planner's own undecided attendance still resolves —
    # they participate, they just aren't charged.
    for rsvp, attendee in participants:
        if (
            attendee.id == planner.attendee_id
            and rsvp.attendance == "unconfirmed"
        ):
            _resolve_attendance(rsvp, present=True)
            await session.commit()

    event.state = _transition(
        EVENT, "event", event.state, "settled"
    )
    event.settled_at = datetime.now(timezone.utc)
    await session.commit()

    return SettlementReport(
        share_cents=share,
        charge_cents=charge,
        shortfall_cents=(share - charge) * len(charged),
        outcomes=tuple(outcomes),
    )
