"""Roster actions: close, mark, cancel, retry, fresh link.

Pins: auto-close on first mark, ownership checks (an admin token
never reaches another event's rows), the cancel money-guard, and
the dangling-retry / re-mint flows against the mocked Stripe.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Payment, Planner, Rsvp
from app.rsvps import get_or_create_rsvp

PLANNER_PHONE = "+15550000001"
SAM_PHONE = "+15550000002"


async def _event(
    session: AsyncSession,
    state: str = "open",
    phone: str = PLANNER_PHONE,
) -> Event:
    planner = Planner(
        name="Noah", phone=phone, stripe_account_id="acct_demo"
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
        state=state,
    )
    session.add(event)
    await session.commit()
    return event


async def _going(
    session: AsyncSession,
    event: Event,
    phone: str = SAM_PHONE,
    name: str = "Sam",
) -> Rsvp:
    rsvp = await get_or_create_rsvp(session, event, name, phone)
    rsvp.state = "going"
    await session.commit()
    return rsvp


async def test_close_button(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _event(db_session)
    resp = await client.post(f"/admin/{event.admin_token}/close")
    assert resp.status_code == 303
    await db_session.refresh(event)
    assert event.state == "closed"
    again = await client.post(f"/admin/{event.admin_token}/close")
    assert again.status_code == 400


async def test_mark_present_auto_closes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """state_machines.md: settlement beginning (first mark) closes
    RSVPs automatically."""
    event = await _event(db_session)  # open
    rsvp = await _going(db_session, event)
    resp = await client.post(
        f"/admin/{event.admin_token}/attendance",
        data={"rsvp_id": str(rsvp.id), "present": "yes"},
    )
    assert resp.status_code == 303
    await db_session.refresh(event)
    await db_session.refresh(rsvp)
    assert event.state == "closed"
    assert rsvp.state == "attended"
    assert rsvp.attendance == "present"


async def test_mark_absent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _event(db_session, state="closed")
    # rsvp created while open, then event closed for the mark
    event.state = "open"
    await db_session.commit()
    rsvp = await _going(db_session, event)
    event.state = "closed"
    await db_session.commit()
    resp = await client.post(
        f"/admin/{event.admin_token}/attendance",
        data={"rsvp_id": str(rsvp.id), "present": "no"},
    )
    assert resp.status_code == 303
    await db_session.refresh(rsvp)
    assert rsvp.state == "no_show"
    assert rsvp.attendance == "absent"


async def test_mark_maybe_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _event(db_session)
    rsvp = await get_or_create_rsvp(
        db_session, event, "Sam", SAM_PHONE
    )
    rsvp.state = "maybe"
    await db_session.commit()
    resp = await client.post(
        f"/admin/{event.admin_token}/attendance",
        data={"rsvp_id": str(rsvp.id), "present": "yes"},
    )
    assert resp.status_code == 400
    assert "tap Going" in resp.text


async def test_mark_foreign_rsvp_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Admin capability is per-event: event A's token must not
    mark event B's rows."""
    event_a = await _event(db_session)
    event_b = await _event(db_session, phone="+15550000009")
    rsvp_b = await _going(db_session, event_b)
    resp = await client.post(
        f"/admin/{event_a.admin_token}/attendance",
        data={"rsvp_id": str(rsvp_b.id), "present": "yes"},
    )
    assert resp.status_code == 404
    await db_session.refresh(rsvp_b)
    assert rsvp_b.state == "going"  # untouched


async def test_mark_after_settled_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _event(db_session)
    rsvp = await _going(db_session, event)
    event.state = "settled"
    await db_session.commit()
    resp = await client.post(
        f"/admin/{event.admin_token}/attendance",
        data={"rsvp_id": str(rsvp.id), "present": "yes"},
    )
    assert resp.status_code == 400


async def test_cancel_confirm_page(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _event(db_session)
    resp = await client.get(f"/admin/{event.admin_token}/cancel")
    assert resp.status_code == 200
    assert "Nothing has been charged" in resp.text


async def test_cancel_happy_path(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _event(db_session)
    resp = await client.post(f"/admin/{event.admin_token}/cancel")
    assert resp.status_code == 303
    await db_session.refresh(event)
    assert event.state == "cancelled"
    stale = await client.get(f"/e/{event.event_token}")
    assert "cancelled" in stale.text
    assert "Nothing was charged" in stale.text


async def test_cancel_blocked_after_money_moved(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A crashed settle can leave collected money on a `closed`
    event; cancelling then would stamp 'nothing charged' onto a
    lie — the guard refuses."""
    event = await _event(db_session, state="closed")
    attendee = Attendee(name="Sam", phone=SAM_PHONE)
    db_session.add(attendee)
    await db_session.flush()
    db_session.add(
        Payment(
            event_id=event.id,
            attendee_id=attendee.id,
            attempt=1,
            state="paid",
            charged_cents=3000,
        )
    )
    await db_session.commit()
    resp = await client.post(f"/admin/{event.admin_token}/cancel")
    assert resp.status_code == 400
    assert "moved money" in resp.text
    await db_session.refresh(event)
    assert event.state == "closed"


async def test_cancel_from_settled_is_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _event(db_session, state="settled")
    resp = await client.post(f"/admin/{event.admin_token}/cancel")
    assert resp.status_code == 400


async def _dangling_payment(
    session: AsyncSession,
    event: Event,
    attendee_id: int,
    cents: int = 3000,
) -> Payment:
    payment = Payment(
        event_id=event.id,
        attendee_id=attendee_id,
        attempt=1,
        state="none",
        charge_requested_at=datetime.now(timezone.utc),
        charge_requested_cents=cents,
    )
    session.add(payment)
    await session.commit()
    return payment


async def test_retry_dangling_lands_paid(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    event = await _event(db_session, state="closed")
    event.state = "open"
    await db_session.commit()
    rsvp = await _going(db_session, event)
    event.state = "closed"
    attendee = await db_session.get(Attendee, rsvp.attendee_id)
    assert attendee is not None
    attendee.stripe_customer_id = "cus_1"
    attendee.stripe_payment_method_id = "pm_1"
    await db_session.commit()
    payment = await _dangling_payment(
        db_session, event, attendee.id
    )
    mock_stripe.PaymentIntent.create_async = AsyncMock(
        return_value=SimpleNamespace(
            id="pi_retry", status="succeeded"
        )
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/retry/{payment.id}"
    )
    assert resp.status_code == 200
    assert "paid" in resp.text
    await db_session.refresh(payment)
    assert payment.state == "paid"
    assert payment.charged_cents == 3000
    # Same-key retry: the stamped amount went to Stripe verbatim
    kwargs = mock_stripe.PaymentIntent.create_async.call_args
    assert kwargs.kwargs["amount"] == 3000
    assert (
        kwargs.kwargs["idempotency_key"] == f"{payment.id}:charge"
    )


async def test_retry_dangling_cardless_mints_link(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    event = await _event(db_session)
    rsvp = await _going(db_session, event)
    event.state = "closed"
    await db_session.commit()
    payment = await _dangling_payment(
        db_session, event, rsvp.attendee_id
    )
    mock_stripe.checkout.Session.create_async = AsyncMock(
        return_value=SimpleNamespace(
            id="cs_new",
            url="https://checkout.stripe.test/pay/cs_new",
        )
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/retry/{payment.id}"
    )
    assert resp.status_code == 200
    assert "https://checkout.stripe.test/pay/cs_new" in resp.text
    assert "sms:" in resp.text
    await db_session.refresh(payment)
    assert payment.state == "unpaid"
    assert payment.stripe_checkout_session_id == "cs_new"


async def test_retry_non_dangling_is_400(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    event = await _event(db_session)
    rsvp = await _going(db_session, event)
    payment = Payment(
        event_id=event.id,
        attendee_id=rsvp.attendee_id,
        attempt=1,
        state="none",  # no stamp: pristine, not dangling
    )
    db_session.add(payment)
    await db_session.commit()
    resp = await client.post(
        f"/admin/{event.admin_token}/retry/{payment.id}"
    )
    assert resp.status_code == 400
    mock_stripe.PaymentIntent.create_async.assert_not_called()


async def test_fresh_link_remints_and_retires(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    event = await _event(db_session)
    rsvp = await _going(db_session, event)
    payment = Payment(
        event_id=event.id,
        attendee_id=rsvp.attendee_id,
        attempt=1,
        state="unpaid",
        state_reason="no_card",
        stripe_checkout_session_id="cs_old",
        charge_requested_at=datetime.now(timezone.utc),
        charge_requested_cents=3000,
    )
    db_session.add(payment)
    await db_session.commit()
    mock_stripe.checkout.Session.retrieve_async = AsyncMock(
        return_value=SimpleNamespace(
            payment_status="unpaid", status="open"
        )
    )
    mock_stripe.checkout.Session.expire_async = AsyncMock()
    mock_stripe.checkout.Session.create_async = AsyncMock(
        return_value=SimpleNamespace(
            id="cs_new2",
            url="https://checkout.stripe.test/pay/cs_new2",
        )
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/link/{payment.id}"
    )
    assert resp.status_code == 200
    assert "cs_new2" in resp.text
    mock_stripe.checkout.Session.expire_async.assert_called_once_with(
        "cs_old"
    )
    await db_session.refresh(payment)
    assert payment.stripe_checkout_session_id == "cs_new2"


async def test_fresh_link_refused_when_old_collected(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    """One payable link per row (2026-07-16): a collected session
    is reconciled by the poller, never papered over."""
    event = await _event(db_session)
    rsvp = await _going(db_session, event)
    payment = Payment(
        event_id=event.id,
        attendee_id=rsvp.attendee_id,
        attempt=1,
        state="unpaid",
        stripe_checkout_session_id="cs_paid",
        charge_requested_at=datetime.now(timezone.utc),
        charge_requested_cents=3000,
    )
    db_session.add(payment)
    await db_session.commit()
    mock_stripe.checkout.Session.retrieve_async = AsyncMock(
        return_value=SimpleNamespace(
            payment_status="paid", status="complete"
        )
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/link/{payment.id}"
    )
    assert resp.status_code == 409
    mock_stripe.checkout.Session.create_async.assert_not_called()
    await db_session.refresh(payment)
    assert payment.stripe_checkout_session_id == "cs_paid"
