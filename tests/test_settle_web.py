"""Settle flow over HTTP: preview math, explicit cap choice,
report with show-once links.

Pins: the preview mirrors settle_event's selection (planner in
the divisor, never charged; settle_default sweep warned; stale
maybes warned), the cap button appears ONLY when actual >
estimate, silence charges actual, and per-attendee containment
surfaces as a dangling row with a retry button.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import stripe as real_stripe
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Payment, Planner, Rsvp
from app.rsvps import get_or_create_rsvp

PLANNER_PHONE = "+15550000001"


async def _event(
    session: AsyncSession, settle_default: str = "assume_all_attended"
) -> tuple[Event, Planner]:
    planner = Planner(
        name="Noah",
        phone=PLANNER_PHONE,
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
        settle_default=settle_default,
    )
    session.add(event)
    await session.commit()
    return event, planner


async def _going(
    session: AsyncSession,
    event: Event,
    name: str,
    phone: str,
    *,
    card: bool = False,
) -> Rsvp:
    rsvp = await get_or_create_rsvp(session, event, name, phone)
    rsvp.state = "going"
    if card:
        attendee = await session.get(Attendee, rsvp.attendee_id)
        assert attendee is not None
        attendee.stripe_customer_id = f"cus_{name.lower()}"
        attendee.stripe_payment_method_id = f"pm_{name.lower()}"
    await session.commit()
    return rsvp


async def _mixed_group(
    session: AsyncSession,
) -> tuple[Event, Planner]:
    """Planner playing (never charged) + Sam with a card + Tia
    cardless: 3 in the split, share floor(12000/3) = 4000 > the
    3000 estimate."""
    event, planner = await _event(session)
    await _going(session, event, "Noah", PLANNER_PHONE)
    await _going(
        session, event, "Sam", "+15550000002", card=True
    )
    await _going(session, event, "Tia", "+15550000003")
    return event, planner


async def test_preview_math_and_warnings(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event, _ = await _mixed_group(db_session)
    page = await client.get(f"/admin/{event.admin_token}/settle")
    assert page.status_code == 200
    assert "3 in the split" in page.text
    assert "never" in page.text  # planner: divisor, never charged
    assert "$40.00" in page.text  # true share
    assert "unmarked" in page.text  # 3 going, none marked yet
    assert "attended (charged)" in page.text  # assume default
    # actual > estimate: both buttons, absorb total named
    assert 'value="actual"' in page.text
    assert 'value="cap"' in page.text
    assert "$20.00" in page.text  # (4000-3000) × 2 chargeable


async def test_preview_single_button_when_within_estimate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event, _ = await _event(db_session)
    for i, name in enumerate(["Ana", "Ben", "Cal", "Dee"]):
        await _going(
            db_session, event, name, f"+1555000010{i}"
        )
    page = await client.get(f"/admin/{event.admin_token}/settle")
    # share == estimate: no choice to make, no cap button
    assert 'value="cap"' not in page.text
    assert "Settle now" in page.text


async def test_preview_warns_about_stale_maybes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event, _ = await _event(db_session)
    rsvp = await get_or_create_rsvp(
        db_session, event, "Mel", "+15550000007"
    )
    rsvp.state = "maybe"
    await db_session.commit()
    page = await client.get(f"/admin/{event.admin_token}/settle")
    assert "still maybe" in page.text
    assert "tap Going" in page.text


async def test_preview_refused_once_settled(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event, _ = await _event(db_session)
    event.state = "settled"
    await db_session.commit()
    page = await client.get(f"/admin/{event.admin_token}/settle")
    assert page.status_code == 400


async def test_settle_actual_mixed_group(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    event, planner = await _mixed_group(db_session)
    mock_stripe.PaymentIntent.create_async = AsyncMock(
        return_value=SimpleNamespace(
            id="pi_sam", status="succeeded"
        )
    )
    mock_stripe.checkout.Session.create_async = AsyncMock(
        return_value=SimpleNamespace(
            id="cs_tia",
            url="https://checkout.stripe.test/pay/cs_tia",
        )
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/settle",
        data={"mode": "actual"},
    )
    assert resp.status_code == 200
    assert "Sam" in resp.text and "paid" in resp.text
    assert "Tia" in resp.text
    assert "https://checkout.stripe.test/pay/cs_tia" in resp.text
    assert "sms:" in resp.text
    await db_session.refresh(event)
    assert event.state == "settled"
    payments = {
        p.attendee_id: p
        for p in (
            await db_session.execute(
                select(Payment).where(
                    Payment.event_id == event.id
                )
            )
        ).scalars()
    }
    assert planner.attendee_id is not None
    assert planner.attendee_id not in payments  # never charged
    states = sorted(p.state for p in payments.values())
    assert states == ["paid", "unpaid"]
    assert all(
        p.charge_requested_cents == 4000
        for p in payments.values()
    )


async def test_settle_cap_absorbs_and_reports(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    event, _ = await _mixed_group(db_session)
    mock_stripe.PaymentIntent.create_async = AsyncMock(
        return_value=SimpleNamespace(
            id="pi_sam", status="succeeded"
        )
    )
    mock_stripe.checkout.Session.create_async = AsyncMock(
        return_value=SimpleNamespace(
            id="cs_tia",
            url="https://checkout.stripe.test/pay/cs_tia",
        )
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/settle",
        data={"mode": "cap"},
    )
    assert resp.status_code == 200
    assert "absorbing" in resp.text
    assert "$20.00" in resp.text  # (4000-3000) × 2
    charged = mock_stripe.PaymentIntent.create_async.call_args
    assert charged.kwargs["amount"] == 3000  # capped at estimate


async def test_settle_rejects_ambiguous_mode(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Absorbing is an ACTIVE choice; anything but the two known
    values is refused, never defaulted (decisions.md 2026-07-15)."""
    event, _ = await _event(db_session)
    resp = await client.post(
        f"/admin/{event.admin_token}/settle",
        data={"mode": "whatever"},
    )
    assert resp.status_code == 400


async def test_double_settle_is_400(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    event, _ = await _event(db_session)
    first = await client.post(
        f"/admin/{event.admin_token}/settle",
        data={"mode": "actual"},
    )
    assert first.status_code == 200
    second = await client.post(
        f"/admin/{event.admin_token}/settle",
        data={"mode": "actual"},
    )
    assert second.status_code == 400


async def test_stripe_error_surfaces_as_dangling_with_retry(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    """Containment is settle_event's: one attendee's API failure
    lands that row dangling; the report shows it loud with a
    retry button."""
    event, _ = await _event(db_session)
    await _going(
        db_session, event, "Sam", "+15550000002", card=True
    )
    mock_stripe.PaymentIntent.create_async = AsyncMock(
        side_effect=real_stripe.StripeError("api down")
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/settle",
        data={"mode": "actual"},
    )
    assert resp.status_code == 200
    assert "dangling" in resp.text
    assert "Retry charge" in resp.text
    payment = (
        await db_session.execute(
            select(Payment).where(Payment.event_id == event.id)
        )
    ).scalar_one()
    assert payment.state == "none"
    assert payment.charge_requested_at is not None  # loud, queryable


async def test_settle_zero_participants_charges_nobody(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    event, _ = await _event(
        db_session, settle_default="mark_all_absent"
    )
    await _going(db_session, event, "Sam", "+15550000002")
    preview = await client.get(
        f"/admin/{event.admin_token}/settle"
    )
    assert "nobody" in preview.text
    resp = await client.post(
        f"/admin/{event.admin_token}/settle",
        data={"mode": "actual"},
    )
    assert resp.status_code == 200
    assert "Nobody was charged" in resp.text
    await db_session.refresh(event)
    assert event.state == "settled"
    payments = (
        (
            await db_session.execute(
                select(Payment).where(
                    Payment.event_id == event.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert payments == []
    mock_stripe.PaymentIntent.create_async.assert_not_called()


async def test_checkout_success_url_from_request_host(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    """Stripe refuses a hosted session without success_url
    (decisions.md 2026-07-16); it must carry the REQUEST host —
    the same origin share links use — never a hardcoded one."""
    event, _ = await _event(db_session)
    await _going(db_session, event, "Tia", "+15550000003")
    mock_stripe.checkout.Session.create_async = AsyncMock(
        return_value=SimpleNamespace(
            id="cs_tia",
            url="https://checkout.stripe.test/pay/cs_tia",
        )
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/settle",
        data={"mode": "actual"},
    )
    assert resp.status_code == 200
    kwargs = (
        mock_stripe.checkout.Session.create_async.await_args.kwargs
    )
    assert kwargs["success_url"] == "http://test/paid"


async def test_link_mint_failure_lands_unpaid_with_fresh_link(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    """A cardless attendee's share resolves to `unpaid` BEFORE the
    link is minted; a mint failure must surface as unpaid with a
    fresh-link button — never as `dangling`, whose retry route
    refuses rows past `none`."""
    event, _ = await _event(db_session)
    await _going(db_session, event, "Tia", "+15550000003")
    mock_stripe.checkout.Session.create_async = AsyncMock(
        side_effect=real_stripe.StripeError("api down")
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/settle",
        data={"mode": "actual"},
    )
    assert resp.status_code == 200
    assert "unpaid" in resp.text
    assert "Get fresh link" in resp.text
    assert "dangling" not in resp.text
    assert "Retry charge" not in resp.text
    payment = (
        await db_session.execute(
            select(Payment).where(Payment.event_id == event.id)
        )
    ).scalar_one()
    assert payment.state == "unpaid"
    assert payment.stripe_checkout_session_id is None
