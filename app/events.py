"""Event lifecycle — the planner's pre-money state writes.

close_rsvps/settle_event stay in app/settlement.py (the money
path); this module owns what happens before money is in play.
Same discipline: every write checks the transition table.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
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
