"""Settlement — the record-first caller.

Owns the DB transactions AROUND app/payments.py (which owns the
Stripe calls): the settle-time state transitions and the intent
stamps commit BEFORE any money moves, so a crash leaves a queryable
dangling row, never an untraced charge (decisions.md 2026-07-13,
2026-07-16). Every state write goes through the tables in
app/state_machines.py — an illegal transition raises, never writes.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Rsvp
from app.state_machines import (
    ATTENDANCE,
    EVENT,
    RSVP,
    can_transition,
)


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
