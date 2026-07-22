"""Attendee-facing polish: the payer's own page tells the truth
(self-poll), and no machine enum is ever shown to an attendee.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import stripe as real_stripe
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Payment, Planner, Rsvp


async def _event_with_rsvp(
    session: AsyncSession,
    *,
    event_state: str,
    rsvp_state: str,
    attendance: str = "unconfirmed",
    session_id: str | None = None,
) -> tuple[Event, Rsvp, Payment | None]:
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
        state=event_state,
    )
    session.add(event)
    attendee = Attendee(name="Sam", phone="6195550123")
    session.add(attendee)
    await session.flush()
    rsvp = Rsvp(
        event_id=event.id,
        attendee_id=attendee.id,
        state=rsvp_state,
        attendance=attendance,
    )
    session.add(rsvp)
    payment = None
    if session_id is not None:
        payment = Payment(
            event_id=event.id,
            attendee_id=attendee.id,
            state="unpaid",
            state_reason="no_card",
            charge_requested_at=datetime.now(timezone.utc),
            charge_requested_cents=3000,
            stripe_checkout_session_id=session_id,
        )
        session.add(payment)
    await session.commit()
    return event, rsvp, payment


async def test_link_payment_shows_on_payers_own_page(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    # The false-copy bug: link paid, planner hasn't reloaded the
    # roster — the payer's own /r/ must not still say they owe.
    (
        _,
        rsvp,
        payment,
    ) = await _event_with_rsvp(
        db_session,
        event_state="settled",
        rsvp_state="attended",
        attendance="present",
        session_id="cs_live",
    )
    mock_stripe.checkout.Session.retrieve_async = AsyncMock(
        return_value=MagicMock(
            payment_status="paid",
            amount_total=3000,
            payment_intent="pi_link",
        )
    )
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert payment is not None
    assert payment.state == "paid"
    assert "Paid" in resp.text and "✓" in resp.text
    assert "will text you a payment link" not in resp.text


async def test_poll_error_keeps_old_copy(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    _, rsvp, payment = await _event_with_rsvp(
        db_session,
        event_state="settled",
        rsvp_state="attended",
        attendance="present",
        session_id="cs_live",
    )
    mock_stripe.checkout.Session.retrieve_async = AsyncMock(
        side_effect=real_stripe.StripeError("down")
    )
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert resp.status_code == 200
    assert payment is not None
    assert payment.state == "unpaid"
    assert "will text you a payment link" in resp.text


async def test_pending_reads_human_on_r(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, rsvp, _ = await _event_with_rsvp(
        db_session, event_state="open", rsvp_state="pending"
    )
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "not answered yet" in resp.text
    assert "pending" not in resp.text
    # Labels flow through variables, so Jinja escapes the
    # apostrophe — the browser still shows "Can't make it".
    assert "Can&#39;t make it" in resp.text
    assert ">declined<" not in resp.text


async def test_no_show_reads_human_on_r(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, rsvp, _ = await _event_with_rsvp(
        db_session,
        event_state="settled",
        rsvp_state="no_show",
        attendance="absent",
    )
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "no_show" not in resp.text
    assert "didn&#39;t play" in resp.text


async def test_me_badge_reads_human(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, rsvp, _ = await _event_with_rsvp(
        db_session, event_state="closed", rsvp_state="attended"
    )
    attendee = await db_session.get(Attendee, rsvp.attendee_id)
    assert attendee is not None
    resp = await client.get(f"/me/{attendee.attendee_token}")
    assert "played" in resp.text
    assert "attended" not in resp.text


async def test_dangling_charge_shows_on_payers_page(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """F5: a player whose saved-card charge is mid-flight (record
    stamped, Stripe unanswered) must see it on their own page — not
    a blank where the money line belongs."""
    event, rsvp, _ = await _event_with_rsvp(
        db_session,
        event_state="settled",
        rsvp_state="attended",
        attendance="present",
    )
    db_session.add(
        Payment(
            event_id=event.id,
            attendee_id=rsvp.attendee_id,
            attempt=1,
            state="none",
            charge_requested_at=datetime.now(timezone.utc),
            charge_requested_cents=3000,
        )
    )
    await db_session.commit()
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert resp.status_code == 200
    assert "charging to your saved card" in resp.text
    assert "$30.00" in resp.text
