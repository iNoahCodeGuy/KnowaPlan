"""RSVP service — the state writes between web routes and models.

Owns the RSVP-side transitions (respond) and the /e/ entry path
(get_or_create_rsvp): find-or-create by phone, mint the /r/
capability by inserting the row, auto-link a playing planner.
Every state write checks the transition table — routes never
write states directly. No money here: a card is optional and
lives on Payment/Attendee (decisions.md 2026-07-15).
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Planner, Rsvp
from app.phone import normalize_phone
from app.state_machines import RSVP, can_transition

# The answers an attendee may pick on /r/ — the response states.
# attended/no_show are the PLANNER's to write (mark_attendance);
# membership is checked BEFORE the table, or a crafted POST with
# choice="attended" would pass can_transition(going, attended)
# and let an attendee mark their own attendance.
CHOICES = ("going", "maybe", "declined")


class EventNotOpen(Exception):
    """Not accepting RSVPs or answer changes — the route renders
    the stale-link page for the event's actual state."""


def _require_open(event: Event) -> None:
    # Service-level guard (the RSVP table has no event context):
    # answers exist and change only while the event is open — this
    # is also what scopes declined -> going (decisions.md
    # 2026-07-08) and lets joins continue through the game
    # (decisions.md 2026-07-15).
    if event.state != "open":
        raise EventNotOpen(event.state)


async def get_or_create_rsvp(
    session: AsyncSession,
    event: Event,
    name: str,
    phone: str,
) -> Rsvp:
    """The /e/ entry: find-or-create the Attendee by phone,
    find-or-create their Rsvp for this event (the insert mints the
    /r/ token), auto-link a playing planner — one transaction.
    Re-entering a known phone returns the SAME row, so a lost /r/
    link is recoverable without accounts. An existing attendee's
    stored name wins over a retyped one."""
    _require_open(event)
    name, phone = name.strip(), phone.strip()
    if not name or not phone:
        raise ValueError("name and phone are required")
    # One spelling per person: autofill formatting must find the
    # same row as typed digits, or the duplicate orphans a saved
    # card and dodges the planner match (app/phone.py).
    phone = normalize_phone(phone)
    attendee = (
        await session.execute(
            select(Attendee).where(Attendee.phone == phone)
        )
    ).scalar_one_or_none()
    if attendee is None:
        attendee = Attendee(name=name, phone=phone)
        session.add(attendee)
        await session.flush()  # assigns attendee.id for the rows below
    planner = await session.get(Planner, event.planner_id)
    try:
        planner_phone = (
            None
            if planner is None
            else normalize_phone(planner.phone)
        )
    except ValueError:
        # A stored planner phone that can't normalize (legacy row)
        # simply never auto-links; the wipe re-mints canonical rows.
        planner_phone = None
    if (
        planner is not None
        and planner_phone == phone
        and planner.attendee_id != attendee.id
    ):
        # A playing planner RSVPs like anyone (decisions.md
        # 2026-07-16); this phone match is what arms settle_event's
        # never-charge-the-planner skip.
        planner.attendee_id = attendee.id
        session.add(planner)
    rsvp = (
        await session.execute(
            select(Rsvp).where(
                Rsvp.event_id == event.id,
                Rsvp.attendee_id == attendee.id,
            )
        )
    ).scalar_one_or_none()
    if rsvp is None:
        rsvp = Rsvp(event_id=event.id, attendee_id=attendee.id)
        session.add(rsvp)
    await session.commit()
    return rsvp


def allowed_choices(rsvp: Rsvp) -> tuple[str, ...]:
    """The answer buttons /r/ may render: legal transitions from
    the current state, response states only. Uniform rule
    (decisions.md 2026-07-21): any answer may become any other
    while the event is open, so every response state offers the
    other two; the UI can never offer an illegal move."""
    return tuple(
        c for c in CHOICES if can_transition(RSVP, rsvp.state, c)
    )


async def respond(
    session: AsyncSession,
    rsvp: Rsvp,
    event: Event,
    choice: str,
) -> Rsvp:
    """Write one answer: membership-checked, open-event-guarded,
    table-checked, one commit. Re-tapping the current answer is a
    no-op, not an illegal self-transition."""
    if choice not in CHOICES:
        raise ValueError(f"not an RSVP answer: {choice!r}")
    _require_open(event)
    if choice == rsvp.state:
        return rsvp
    if not can_transition(RSVP, rsvp.state, choice):
        raise ValueError(
            f"illegal rsvp move {rsvp.state!r} -> {choice!r}"
        )
    rsvp.state = choice
    session.add(rsvp)
    await session.commit()
    return rsvp
