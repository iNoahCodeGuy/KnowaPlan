"""Event lifecycle — the planner's pre-money state writes.

close_rsvps/settle_event stay in app/settlement.py (the money
path); this module owns what happens before money is in play.
Same discipline: every write checks the transition table.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Payment
from app.state_machines import EVENT, can_transition


def _transition(current: str, dst: str) -> str:
    if not can_transition(EVENT, current, dst):
        raise ValueError(
            f"illegal event move {current!r} -> {dst!r}"
        )
    return dst


async def open_rsvps(
    session: AsyncSession, event: Event
) -> Event:
    """draft -> open: the planner shares the link
    (state_machines.md). The estimate freeze that belongs to this
    moment ships with the event-edit service (parked)."""
    event.state = _transition(event.state, "open")
    session.add(event)
    await session.commit()
    return event


async def cancel_event(
    session: AsyncSession, event: Event
) -> Event:
    """open|closed -> cancelled. Pre-settlement nothing has been
    charged (no holds — decisions.md 2026-07-15), so this is a
    pure state write — but a CRASHED settle can move money while
    the event is still `closed`, and cancelling then would stamp
    "nothing charged" onto an event where money moved. Refuse
    unless every Payment row is pristine (state `none`, no
    record-first stamp). Post-settle reversals go through refunds,
    never cancellation (state_machines.md)."""
    payments = (
        await session.execute(
            select(Payment).where(Payment.event_id == event.id)
        )
    ).scalars()
    if any(
        p.state != "none" or p.charge_requested_at is not None
        for p in payments
    ):
        raise ValueError(
            "a settle run already moved money for this event — "
            "finish settling (retry any flagged rows) instead of "
            "cancelling"
        )
    event.state = _transition(event.state, "cancelled")
    session.add(event)
    await session.commit()
    return event
