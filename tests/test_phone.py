"""Phone canonicalization (decisions.md 2026-07-21, entry
pending): one spelling per person. The split identity this
prevents is money-relevant twice over — a duplicate attendee
orphans a saved card, and a formatting mismatch can dodge the
never-charge-the-planner match, charging the planner's own card.
"""
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Planner
from app.phone import normalize_phone
from app.rsvps import get_or_create_rsvp


@pytest.mark.parametrize(
    "raw",
    [
        "(619) 555-0123",
        "+1 619-555-0123",
        "1.619.555.0123",
        "6195550123",
        " 619 555 0123 ",
    ],
)
def test_every_spelling_collapses_to_digits(raw: str) -> None:
    assert normalize_phone(raw) == "6195550123"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "abc",
        "12",
        "70264298016",  # the real 11-digit typo from the live test
        "+44 20 7946 0958",  # international: out of scope for v0
    ],
)
def test_wrong_shapes_raise(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(raw)


async def _open_event(
    session: AsyncSession, planner_phone: str
) -> Event:
    planner = Planner(
        name="Noah",
        phone=planner_phone,
        stripe_account_id="acct_demo",
    )
    session.add(planner)
    await session.flush()
    event = Event(
        planner_id=planner.id,
        title="Tuesday pickleball",
        starts_at=datetime(2026, 7, 21, 18, tzinfo=timezone.utc),
        total_cost_cents=12000,
        goal_attendance=4,
        estimated_share_cents=3000,
        state="open",
    )
    session.add(event)
    await session.commit()
    return event


async def test_autofill_and_typed_are_one_person(
    db_session: AsyncSession,
) -> None:
    # THE regression: autofill formatting on one visit, bare
    # digits on the next — same row, same /r/ capability back.
    event = await _open_event(db_session, "7073190951")
    first = await get_or_create_rsvp(
        db_session, event, "Sam", "(619) 555-0123"
    )
    second = await get_or_create_rsvp(
        db_session, event, "Sam", "6195550123"
    )
    assert first.id == second.id
    count = (
        await db_session.execute(
            select(func.count()).select_from(Attendee)
        )
    ).scalar_one()
    assert count == 1
    attendee = (
        await db_session.execute(select(Attendee))
    ).scalar_one()
    assert attendee.phone == "6195550123"


async def test_planner_match_survives_formatting(
    db_session: AsyncSession,
) -> None:
    # The money pin: planner row stored with autofill formatting,
    # planner RSVPs with bare digits — the auto-link must still
    # arm, or settle charges the planner's own card.
    event = await _open_event(db_session, "(707) 319-0951")
    rsvp = await get_or_create_rsvp(
        db_session, event, "Noah", "7073190951"
    )
    planner = await db_session.get(Planner, event.planner_id)
    assert planner is not None
    assert planner.attendee_id == rsvp.attendee_id


async def test_rsvp_form_bad_phone_is_a_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session, "7073190951")
    resp = await client.post(
        f"/e/{event.event_token}/rsvp",
        data={"name": "Sam", "phone": "12"},
    )
    assert resp.status_code == 400
    assert "10" in resp.text  # the fix-it hint reaches the form


async def test_create_form_bad_phone_is_a_400(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLANNER_ACCOUNT_ID", "acct_demo")
    monkeypatch.setenv("CREATE_PASSWORD", "letmein")
    resp = await client.post(
        "/events",
        data={
            "planner_name": "Noah",
            "planner_phone": "531",
            "title": "Tuesday",
            "starts_at": "2026-07-22T18:00",
            "total_cost_dollars": "120",
            "goal_attendance": "4",
            "settle_default": "assume_all_attended",
            "create_password": "letmein",
        },
    )
    assert resp.status_code == 400
    assert "10" in resp.text
