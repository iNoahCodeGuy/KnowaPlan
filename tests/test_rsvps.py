"""RSVP service behavior (app/rsvps.py).

Pins: the /e/ entry path (find-or-create + token + planner
auto-link + lost-link recovery), the response matrix with its
event-open guard (decisions.md 2026-07-08/15), and the refusal
of self-marked attendance.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Planner, Rsvp
from app.rsvps import (
    EventNotOpen,
    allowed_choices,
    get_or_create_rsvp,
    respond,
)

PLANNER_PHONE = "+15550000001"
SAM_PHONE = "+15550000002"


async def _planner(session: AsyncSession) -> Planner:
    planner = Planner(
        name="Noah",
        phone=PLANNER_PHONE,
        stripe_account_id="acct_test",
    )
    session.add(planner)
    await session.commit()
    return planner


async def _event(
    session: AsyncSession, planner: Planner, state: str = "open"
) -> Event:
    event = Event(
        planner_id=planner.id,
        title="Tuesday pickleball",
        starts_at=datetime(2026, 7, 21, 18, tzinfo=timezone.utc),
        total_cost_cents=12000,
        goal_attendance=4,
        estimated_share_cents=3000,
        state=state,
    )
    session.add(event)
    await session.commit()
    return event


async def test_entry_creates_attendee_and_pending_rsvp(
    db_session: AsyncSession,
) -> None:
    planner = await _planner(db_session)
    event = await _event(db_session, planner)
    rsvp = await get_or_create_rsvp(
        db_session, event, "Sam", SAM_PHONE
    )
    assert rsvp.state == "pending"
    assert len(rsvp.rsvp_token) == 22


async def test_reentry_returns_same_row_and_keeps_name(
    db_session: AsyncSession,
) -> None:
    """Lost-link recovery: same phone → same row, same /r/ token;
    the stored name wins over a retyped one."""
    planner = await _planner(db_session)
    event = await _event(db_session, planner)
    first = await get_or_create_rsvp(
        db_session, event, "Sam", SAM_PHONE
    )
    again = await get_or_create_rsvp(
        db_session, event, "Samuel", SAM_PHONE
    )
    assert again.id == first.id
    assert again.rsvp_token == first.rsvp_token
    attendee = await db_session.get(Attendee, again.attendee_id)
    assert attendee is not None and attendee.name == "Sam"


@pytest.mark.parametrize("state", ["draft", "closed"])
async def test_entry_requires_open_event(
    db_session: AsyncSession, state: str
) -> None:
    planner = await _planner(db_session)
    event = await _event(db_session, planner, state=state)
    with pytest.raises(EventNotOpen):
        await get_or_create_rsvp(
            db_session, event, "Sam", SAM_PHONE
        )


async def test_planner_phone_auto_links(
    db_session: AsyncSession,
) -> None:
    """The phone match arms settle_event's never-charge-the-planner
    skip (decisions.md 2026-07-16); re-entry stays linked."""
    planner = await _planner(db_session)
    event = await _event(db_session, planner)
    rsvp = await get_or_create_rsvp(
        db_session, event, "Noah", PLANNER_PHONE
    )
    assert planner.attendee_id == rsvp.attendee_id
    await get_or_create_rsvp(
        db_session, event, "Noah", PLANNER_PHONE
    )
    assert planner.attendee_id == rsvp.attendee_id


async def test_stranger_phone_does_not_link(
    db_session: AsyncSession,
) -> None:
    planner = await _planner(db_session)
    event = await _event(db_session, planner)
    await get_or_create_rsvp(db_session, event, "Sam", SAM_PHONE)
    assert planner.attendee_id is None


@pytest.mark.parametrize(
    ("start", "choice"),
    [
        ("pending", "going"),
        ("pending", "maybe"),
        ("pending", "declined"),
        ("maybe", "going"),
        ("maybe", "declined"),
        ("declined", "going"),
    ],
)
async def test_legal_responses(
    db_session: AsyncSession, start: str, choice: str
) -> None:
    planner = await _planner(db_session)
    event = await _event(db_session, planner)
    rsvp = await get_or_create_rsvp(
        db_session, event, "Sam", SAM_PHONE
    )
    rsvp.state = start
    await db_session.commit()
    result = await respond(db_session, rsvp, event, choice)
    assert result.state == choice


@pytest.mark.parametrize("choice", ["declined", "maybe"])
async def test_going_backs_out_self_service(
    db_session: AsyncSession, choice: str
) -> None:
    """Uniform rule (decisions.md 2026-07-21): backing out is
    self-service while the event is open — the hold-era
    planner-territory rule is retired (no hold to release)."""
    planner = await _planner(db_session)
    event = await _event(db_session, planner)
    rsvp = await get_or_create_rsvp(
        db_session, event, "Sam", SAM_PHONE
    )
    rsvp.state = "going"
    await db_session.commit()
    result = await respond(db_session, rsvp, event, choice)
    assert result.state == choice


async def test_same_choice_is_noop(
    db_session: AsyncSession,
) -> None:
    planner = await _planner(db_session)
    event = await _event(db_session, planner)
    rsvp = await get_or_create_rsvp(
        db_session, event, "Sam", SAM_PHONE
    )
    rsvp.state = "going"
    await db_session.commit()
    result = await respond(db_session, rsvp, event, "going")
    assert result.state == "going"


async def test_no_changes_after_close(
    db_session: AsyncSession,
) -> None:
    """declined → going is legal in the table but only while the
    event is open (decisions.md 2026-07-08)."""
    planner = await _planner(db_session)
    event = await _event(db_session, planner)
    rsvp = await get_or_create_rsvp(
        db_session, event, "Sam", SAM_PHONE
    )
    rsvp.state = "declined"
    event.state = "closed"
    await db_session.commit()
    with pytest.raises(EventNotOpen):
        await respond(db_session, rsvp, event, "going")


async def test_attendee_cannot_self_mark_attendance(
    db_session: AsyncSession,
) -> None:
    """choice='attended' would pass the transition table from
    'going' — the CHOICES membership check must refuse it first."""
    planner = await _planner(db_session)
    event = await _event(db_session, planner)
    rsvp = await get_or_create_rsvp(
        db_session, event, "Sam", SAM_PHONE
    )
    rsvp.state = "going"
    await db_session.commit()
    with pytest.raises(ValueError):
        await respond(db_session, rsvp, event, "attended")


def test_allowed_choices_per_state() -> None:
    """What /r/ may render, straight from the table — uniform
    rule (decisions.md 2026-07-21): every response state offers
    the other two."""
    expectations = {
        "pending": ("going", "maybe", "declined"),
        "maybe": ("going", "declined"),
        "declined": ("going", "maybe"),
        "going": ("maybe", "declined"),
    }
    for state, expected in expectations.items():
        assert allowed_choices(Rsvp(state=state)) == expected


@pytest.mark.parametrize(
    ("name", "phone"), [("", SAM_PHONE), ("Sam", "   ")]
)
async def test_blank_identity_refused(
    db_session: AsyncSession, name: str, phone: str
) -> None:
    planner = await _planner(db_session)
    event = await _event(db_session, planner)
    with pytest.raises(ValueError):
        await get_or_create_rsvp(db_session, event, name, phone)
