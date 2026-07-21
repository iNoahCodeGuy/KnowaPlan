"""Courtside polish: iOS-form sms: links, the card-save fear
sentence, autofill-inviting inputs. Each pins a piece of the
7/29 night: collection runs on the planner's iPhone (a ?body
sms: opens Messages EMPTY there), card saves stall on the
unanswered "what if I can't make it", and tel inputs are only
safe because normalize_phone absorbs whatever autofill pastes.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Planner, Rsvp

TEMPLATES = Path(__file__).parent.parent / "app" / "templates"


@pytest.mark.parametrize(
    "template", ["settle_report.html", "link_result.html"]
)
def test_sms_links_are_ios_form(template: str) -> None:
    # Source-level on purpose: the href's SHAPE is the contract.
    source = (TEMPLATES / template).read_text()
    assert "sms:+1{{ attendee.phone }}&body=" in source
    assert "?body=" not in source


async def _going_rsvp(
    session: AsyncSession, *, with_card: bool = False
) -> Rsvp:
    planner = Planner(
        name="Noah",
        phone="7073190951",
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
    attendee = Attendee(
        name="Sam",
        phone="6195550123",
        stripe_payment_method_id=(
            "pm_test" if with_card else None
        ),
    )
    session.add(attendee)
    await session.flush()
    rsvp = Rsvp(
        event_id=event.id,
        attendee_id=attendee.id,
        state="going",
    )
    session.add(rsvp)
    await session.commit()
    return rsvp


async def test_card_pitch_answers_the_no_show_fear(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_x")
    rsvp = await _going_rsvp(db_session)
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "only charged if you play" in resp.text


async def test_card_on_file_repeats_only_if_you_play(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    rsvp = await _going_rsvp(db_session, with_card=True)
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "only if you play" in resp.text


async def test_phone_inputs_invite_autofill(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    rsvp = await _going_rsvp(db_session)
    event = await db_session.get(Event, rsvp.event_id)
    assert event is not None
    for url in (f"/e/{event.event_token}", "/"):
        resp = await client.get(url)
        assert 'type="tel"' in resp.text
        assert 'inputmode="tel"' in resp.text
        assert 'autocomplete="tel"' in resp.text
