"""/me/{token} — the cross-event "your events" page.

Pins the two properties the design leans on (decisions.md entry
pending): the page is VIEW-ONLY (no /r/ token or link ever
renders, so a leaked bookmark cannot answer for anyone), and the
attendee token is its own purpose (an rsvp token is dead on /me/,
a miss is the uniform 404).
"""
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Planner, Rsvp

PLANNER_PHONE = "+15550000001"
SAM_PHONE = "+15550000002"
RILEY_PHONE = "+15550000003"


async def _planner(session: AsyncSession) -> Planner:
    planner = Planner(
        name="Noah",
        phone=PLANNER_PHONE,
        stripe_account_id="acct_demo",
    )
    session.add(planner)
    await session.commit()
    return planner


async def _event(
    session: AsyncSession,
    planner_id: int,
    title: str,
    state: str,
    day: int = 21,
) -> Event:
    event = Event(
        planner_id=planner_id,
        title=title,
        starts_at=datetime(2026, 7, day, 18, tzinfo=timezone.utc),
        total_cost_cents=12000,
        goal_attendance=4,
        estimated_share_cents=3000,
        state=state,
    )
    session.add(event)
    await session.commit()
    return event


async def _attendee(
    session: AsyncSession, name: str, phone: str
) -> Attendee:
    attendee = Attendee(name=name, phone=phone)
    session.add(attendee)
    await session.commit()
    return attendee


async def _rsvp(
    session: AsyncSession,
    event: Event,
    attendee: Attendee,
    state: str = "going",
) -> Rsvp:
    rsvp = Rsvp(
        event_id=event.id, attendee_id=attendee.id, state=state
    )
    session.add(rsvp)
    await session.commit()
    return rsvp


async def test_me_page_unknown_token_404(
    client: AsyncClient,
) -> None:
    resp = await client.get("/me/nope")
    assert resp.status_code == 404


async def test_rsvp_token_is_dead_on_me(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # One token per purpose (decisions.md 2026-07-16): /me/ reads
    # ONLY attendee_token — a valid rsvp token must not open it.
    planner = await _planner(db_session)
    event = await _event(db_session, planner.id, "Tues", "open")
    sam = await _attendee(db_session, "Sam", SAM_PHONE)
    rsvp = await _rsvp(db_session, event, sam)
    resp = await client.get(f"/me/{rsvp.rsvp_token}")
    assert resp.status_code == 404


async def test_me_lists_open_and_closed_events_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    planner = await _planner(db_session)
    sam = await _attendee(db_session, "Sam", SAM_PHONE)
    shown_states = {"open": "Open game", "closed": "Closed game"}
    hidden_states = {
        "settled": "Settled game",
        "cancelled": "Cancelled game",
    }
    for state, title in {**shown_states, **hidden_states}.items():
        event = await _event(db_session, planner.id, title, state)
        await _rsvp(db_session, event, sam)
    resp = await client.get(f"/me/{sam.attendee_token}")
    assert resp.status_code == 200
    for title in shown_states.values():
        assert title in resp.text
    for title in hidden_states.values():
        assert title not in resp.text


async def test_me_events_sorted_by_start(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    planner = await _planner(db_session)
    sam = await _attendee(db_session, "Sam", SAM_PHONE)
    later = await _event(
        db_session, planner.id, "Later game", "open", day=25
    )
    sooner = await _event(
        db_session, planner.id, "Sooner game", "open", day=22
    )
    await _rsvp(db_session, later, sam)
    await _rsvp(db_session, sooner, sam)
    resp = await client.get(f"/me/{sam.attendee_token}")
    assert resp.text.index("Sooner game") < resp.text.index(
        "Later game"
    )


async def test_me_shows_only_this_attendees_events(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    planner = await _planner(db_session)
    sams_game = await _event(
        db_session, planner.id, "Sams game", "open"
    )
    rileys_game = await _event(
        db_session, planner.id, "Rileys game", "open", day=22
    )
    sam = await _attendee(db_session, "Sam", SAM_PHONE)
    riley = await _attendee(db_session, "Riley", RILEY_PHONE)
    await _rsvp(db_session, sams_game, sam)
    await _rsvp(db_session, rileys_game, riley)
    resp = await client.get(f"/me/{sam.attendee_token}")
    assert "Sams game" in resp.text
    assert "Rileys game" not in resp.text


async def test_me_page_never_leaks_rsvp_tokens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # View-only as a CONTRACT: with no /r/ token in the page, a
    # leaked /me/ link shows a schedule but cannot change an
    # answer — the per-event blast radius of decisions.md
    # 2026-07-16 is preserved.
    planner = await _planner(db_session)
    event = await _event(db_session, planner.id, "Tues", "open")
    sam = await _attendee(db_session, "Sam", SAM_PHONE)
    rsvp = await _rsvp(db_session, event, sam)
    resp = await client.get(f"/me/{sam.attendee_token}")
    assert resp.status_code == 200
    assert rsvp.rsvp_token not in resp.text
    assert "/r/" not in resp.text


async def test_rsvp_page_links_me_page(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    planner = await _planner(db_session)
    event = await _event(db_session, planner.id, "Tues", "open")
    sam = await _attendee(db_session, "Sam", SAM_PHONE)
    rsvp = await _rsvp(db_session, event, sam)
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert resp.status_code == 200
    assert f"/me/{sam.attendee_token}" in resp.text
