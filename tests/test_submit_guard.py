"""Submit guard — dead buttons on double-tap, wait copy on
settle. The JS behavior itself is verified by hand on a real
phone (freeze rehearsal); these pin what the server must ship
for that behavior to exist at all.
"""
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Planner, Rsvp


async def test_every_page_ships_the_submit_guard(
    client: AsyncClient,
) -> None:
    # base.html carries it, so the create form is any-page proof.
    resp = await client.get("/")
    assert 'addEventListener("submit"' in resp.text
    assert "setTimeout" in resp.text  # deferred: keeps name/value


async def test_settle_form_carries_wait_message(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    planner = Planner(
        name="Noah",
        phone="7073190951",
        stripe_account_id="acct_demo",
    )
    db_session.add(planner)
    await db_session.flush()
    event = Event(
        planner_id=planner.id,
        title="Tuesday pickleball",
        starts_at=datetime(2026, 7, 21, 18, tzinfo=timezone.utc),
        total_cost_cents=12000,
        goal_attendance=4,
        estimated_share_cents=3000,
        state="closed",
    )
    db_session.add(event)
    attendee = Attendee(name="Sam", phone="6195550123")
    db_session.add(attendee)
    await db_session.flush()
    db_session.add(
        Rsvp(
            event_id=event.id,
            attendee_id=attendee.id,
            state="attended",
            attendance="present",
        )
    )
    await db_session.commit()
    resp = await client.get(f"/admin/{event.admin_token}/settle")
    assert "data-wait=" in resp.text
    assert "keep this" in resp.text


async def test_sub_minimum_share_blocks_the_preview(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    planner = Planner(
        name="Noah",
        phone="7073190952",
        stripe_account_id="acct_demo",
    )
    db_session.add(planner)
    await db_session.flush()
    event = Event(
        planner_id=planner.id,
        title="Tiny split",
        starts_at=datetime(2026, 7, 21, 18, tzinfo=timezone.utc),
        total_cost_cents=100,
        goal_attendance=3,
        estimated_share_cents=33,
        state="closed",
    )
    db_session.add(event)
    # Three present: share = floor(100/3) = 33¢ — under the floor.
    for phone in ("6195550124", "6195550125", "6195550126"):
        attendee = Attendee(name=f"Sam{phone[-1]}", phone=phone)
        db_session.add(attendee)
        await db_session.flush()
        db_session.add(
            Rsvp(
                event_id=event.id,
                attendee_id=attendee.id,
                state="attended",
                attendance="present",
            )
        )
    await db_session.commit()
    resp = await client.get(f"/admin/{event.admin_token}/settle")
    # The preview never offers a settle the service will refuse.
    assert "50¢ minimum" in resp.text
    assert 'name="mode"' not in resp.text
