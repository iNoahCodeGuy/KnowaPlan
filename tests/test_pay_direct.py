"""Direct payment (Venmo/Zelle/cash) — claim, confirm, display.

Pins the money-relevant contracts of decisions.md (2026-07-21,
entry pending): a claim is a FLAG on unpaid, never a state; the
planner's confirm expires any live link BEFORE the row says paid
(inverse of record-first — a paid row must never leave a live
collection path behind); an already-collected link REFUSES; and
the double-pay (Stripe-paid + claim) is displayed to both sides.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import stripe as real_stripe
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Payment, Planner, Rsvp
from app.payments import mark_paid_direct

PLANNER_PHONE = "+15550000001"
SAM_PHONE = "+15550000002"


async def _settled_unpaid(
    session: AsyncSession,
    *,
    handles: str | None = "Venmo @noah",
    session_id: str | None = None,
    claimed_via: str | None = None,
) -> tuple[Event, Rsvp, Payment, Attendee]:
    """A settled event with one unpaid attendee — the state every
    direct-payment path starts from."""
    planner = Planner(
        name="Noah",
        phone=PLANNER_PHONE,
        stripe_account_id="acct_demo",
        payment_handles=handles,
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
        state="settled",
    )
    session.add(event)
    attendee = Attendee(name="Sam", phone=SAM_PHONE)
    session.add(attendee)
    await session.flush()
    rsvp = Rsvp(
        event_id=event.id,
        attendee_id=attendee.id,
        state="attended",
        attendance="present",
    )
    session.add(rsvp)
    payment = Payment(
        event_id=event.id,
        attendee_id=attendee.id,
        state="unpaid",
        state_reason="no_card",
        charge_requested_at=datetime.now(timezone.utc),
        charge_requested_cents=3000,
        stripe_checkout_session_id=session_id,
        claimed_at=(
            datetime.now(timezone.utc) if claimed_via else None
        ),
        claimed_via=claimed_via,
    )
    session.add(payment)
    await session.commit()
    return event, rsvp, payment, attendee


# --- mark_paid_direct (service) ----------------------------------


async def test_mark_paid_flips_and_stamps_no_stripe(
    db_session: AsyncSession, mock_stripe: MagicMock
) -> None:
    # No stored link -> no Stripe call at all.
    _, _, payment, _ = await _settled_unpaid(
        db_session, claimed_via="venmo"
    )
    await mark_paid_direct(payment)
    assert payment.state == "paid"
    assert payment.paid_direct_at is not None
    assert payment.state_reason == "venmo"
    assert payment.charged_cents is None
    mock_stripe.checkout.Session.retrieve_async.assert_not_called()


async def test_mark_paid_expires_live_link_first(
    db_session: AsyncSession, mock_stripe: MagicMock
) -> None:
    _, _, payment, _ = await _settled_unpaid(
        db_session, session_id="cs_live"
    )
    order: list[str] = []

    async def _retrieve(sid: str) -> MagicMock:
        return MagicMock(payment_status="unpaid", status="open")

    async def _expire(sid: str) -> MagicMock:
        order.append(f"expire:{sid}:{payment.state}")
        return MagicMock()

    mock_stripe.checkout.Session.retrieve_async = AsyncMock(
        side_effect=_retrieve
    )
    mock_stripe.checkout.Session.expire_async = AsyncMock(
        side_effect=_expire
    )
    await mark_paid_direct(payment)
    # The expire ran while the row still said unpaid — the link
    # died BEFORE the state write, never after.
    assert order == ["expire:cs_live:unpaid"]
    assert payment.state == "paid"
    assert payment.state_reason == "direct"  # no claim preceded


async def test_mark_paid_refuses_collected_link(
    db_session: AsyncSession, mock_stripe: MagicMock
) -> None:
    _, _, payment, _ = await _settled_unpaid(
        db_session, session_id="cs_live"
    )
    mock_stripe.checkout.Session.retrieve_async = AsyncMock(
        return_value=MagicMock(
            payment_status="paid", status="complete"
        )
    )
    with pytest.raises(ValueError, match="already paid"):
        await mark_paid_direct(payment)
    assert payment.state == "unpaid"
    assert payment.paid_direct_at is None
    mock_stripe.checkout.Session.expire_async.assert_not_called()


@pytest.mark.parametrize("state", ["none", "paid", "abandoned"])
async def test_mark_paid_refuses_non_unpaid(
    db_session: AsyncSession,
    mock_stripe: MagicMock,
    state: str,
) -> None:
    _, _, payment, _ = await _settled_unpaid(db_session)
    payment.state = state
    with pytest.raises(ValueError, match="unpaid"):
        await mark_paid_direct(payment)


async def test_mark_paid_stripe_error_leaves_unpaid(
    db_session: AsyncSession, mock_stripe: MagicMock
) -> None:
    _, _, payment, _ = await _settled_unpaid(
        db_session, session_id="cs_live"
    )
    mock_stripe.checkout.Session.retrieve_async = AsyncMock(
        side_effect=real_stripe.StripeError("down")
    )
    with pytest.raises(real_stripe.StripeError):
        await mark_paid_direct(payment)
    assert payment.state == "unpaid"
    assert payment.paid_direct_at is None


# --- claim + confirm + reject (web) ------------------------------


async def test_claim_sets_flag_and_roster_chip(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event, rsvp, payment, _ = await _settled_unpaid(db_session)
    resp = await client.post(
        f"/r/{rsvp.rsvp_token}/claim", data={"via": "venmo"}
    )
    assert resp.status_code == 303
    assert payment.claimed_via == "venmo"
    assert payment.state == "unpaid"  # a claim collects nothing
    roster = await client.get(f"/admin/{event.admin_token}")
    assert "says they paid" in roster.text
    assert "They paid me" in roster.text
    assert "Didn't get it" in roster.text


async def test_claim_rejects_bogus_via(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, rsvp, payment, _ = await _settled_unpaid(db_session)
    resp = await client.post(
        f"/r/{rsvp.rsvp_token}/claim", data={"via": "paypal"}
    )
    assert resp.status_code == 400
    assert payment.claimed_at is None


async def test_claim_without_unpaid_row_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, rsvp, payment, _ = await _settled_unpaid(db_session)
    payment.state = "paid"
    await db_session.commit()
    resp = await client.post(
        f"/r/{rsvp.rsvp_token}/claim", data={"via": "venmo"}
    )
    assert resp.status_code == 400


async def test_confirm_route_marks_paid(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event, _, payment, _ = await _settled_unpaid(
        db_session, claimed_via="zelle"
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/mark-paid/{payment.id}"
    )
    assert resp.status_code == 303
    assert payment.state == "paid"
    roster = await client.get(f"/admin/{event.admin_token}")
    assert "zelle" in roster.text
    assert "$30.00 direct" in roster.text


async def test_reject_clears_claim(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event, _, payment, _ = await _settled_unpaid(
        db_session, claimed_via="venmo"
    )
    resp = await client.post(
        f"/admin/{event.admin_token}/claim-reject/{payment.id}"
    )
    assert resp.status_code == 303
    assert payment.claimed_at is None
    assert payment.claimed_via is None
    assert payment.state == "unpaid"


async def test_mark_paid_wrong_event_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event, _, payment, _ = await _settled_unpaid(db_session)
    resp = await client.post(
        f"/admin/{event.event_token}/mark-paid/{payment.id}"
    )
    assert resp.status_code == 404  # event token dead on admin


# --- display -----------------------------------------------------


async def test_r_page_offers_direct_pay_with_handles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, rsvp, _, _ = await _settled_unpaid(db_session)
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "Venmo @noah" in resp.text
    assert "I paid Noah directly" in resp.text


async def test_r_page_hides_direct_pay_without_handles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, rsvp, _, _ = await _settled_unpaid(
        db_session, handles=None
    )
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "directly" not in resp.text


async def test_r_page_shows_waiting_after_claim(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, rsvp, _, _ = await _settled_unpaid(
        db_session, claimed_via="venmo"
    )
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "waiting on their" in resp.text
    # The claim form is gone — one pending claim at a time.
    assert "I paid Noah directly" not in resp.text


async def test_r_page_paid_direct_copy(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, rsvp, payment, _ = await _settled_unpaid(db_session)
    await mark_paid_direct(payment)
    await db_session.commit()
    resp = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "marked you paid" in resp.text


# --- navigation sweep (per-role home links) ----------------------


async def test_admin_subpage_carries_event_home(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event, _, _, _ = await _settled_unpaid(db_session)
    event.state = "closed"
    await db_session.commit()
    resp = await client.get(f"/admin/{event.admin_token}/settle")
    assert f"/admin/{event.admin_token}" in resp.text
    assert "Event home" in resp.text


async def test_error_and_not_found_offer_go_back(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, rsvp, _, _ = await _settled_unpaid(db_session)
    error = await client.post(
        f"/r/{rsvp.rsvp_token}/claim", data={"via": "paypal"}
    )
    assert "Go back" in error.text
    missing = await client.get("/me/nope")
    assert "Go back" in missing.text


async def test_double_pay_banner_both_sides(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Stripe collected AND a claim is set: the one double-pay the
    # app can see (the claim survives the poll flip on purpose).
    event, rsvp, payment, _ = await _settled_unpaid(
        db_session, claimed_via="venmo"
    )
    payment.state = "paid"
    payment.charged_cents = 3000
    payment.stripe_payment_intent_id = "pi_double"
    await db_session.commit()
    roster = await client.get(f"/admin/{event.admin_token}")
    assert "refund one" in roster.text
    own = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "owes one back" in own.text
