"""Attendee-facing pages: /e/ entry, /r/ responses, card island.

Pins: capability separation (an admin token is dead on /e/),
state-appropriate pages (open form / stale wording), 409 for
POSTs that lose a race with a close, the going-can't-back-out
rendering, and the SetupIntent save flow — minting, finalizing,
failure copy — against the mocked Stripe module.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import stripe as real_stripe
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Payment, Planner, Rsvp
from app.rsvps import get_or_create_rsvp

PLANNER_PHONE = "+15550000001"
SAM_PHONE = "+15550000002"


@pytest.fixture
def stripe_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Card-save routes pre-check the secret key; tests of the
    happy path opt in (the mock still intercepts every call)."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_mocked")


@pytest.fixture
def publishable_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_mocked")


async def _open_event(
    session: AsyncSession, state: str = "open"
) -> Event:
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
        state=state,
    )
    session.add(event)
    await session.commit()
    return event


async def _sam_rsvp(
    session: AsyncSession, event: Event, state: str = "pending"
) -> Rsvp:
    rsvp = await get_or_create_rsvp(session, event, "Sam", SAM_PHONE)
    if state != "pending":
        rsvp.state = state
        await session.commit()
    return rsvp


# --- /e/ ---------------------------------------------------------


async def test_event_page_unknown_token_404(
    client: AsyncClient,
) -> None:
    resp = await client.get("/e/deadbeefdeadbeefdead")
    assert resp.status_code == 404
    assert "doesn't point anywhere" in resp.text


async def test_admin_token_is_dead_on_e(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """One token per purpose: the admin capability must not open
    the event page (decisions.md 2026-07-13) — the lookup is
    column-scoped, so this is a plain 404."""
    event = await _open_event(db_session)
    resp = await client.get(f"/e/{event.admin_token}")
    assert resp.status_code == 404


async def test_event_page_draft_has_no_form(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session, state="draft")
    resp = await client.get(f"/e/{event.event_token}")
    assert resp.status_code == 200
    assert "isn't open for RSVPs yet" in resp.text
    assert 'name="phone"' not in resp.text


async def test_event_page_open_form_and_estimate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    resp = await client.get(f"/e/{event.event_token}")
    assert 'name="phone"' in resp.text
    assert "$30.00" in resp.text
    assert "Nothing is charged now" in resp.text


async def test_event_page_closed_is_stale(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session, state="closed")
    resp = await client.get(f"/e/{event.event_token}")
    assert "RSVPs are closed" in resp.text
    assert 'name="phone"' not in resp.text


async def test_start_rsvp_happy_path(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    resp = await client.post(
        f"/e/{event.event_token}/rsvp",
        data={"name": "Sam", "phone": SAM_PHONE},
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/r/")
    page = await client.get(resp.headers["location"])
    assert "Hi Sam" in page.text
    # Raw enums never face attendees (2026-07-21 label map)
    assert "not answered yet" in page.text


async def test_start_rsvp_blank_name_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    resp = await client.post(
        f"/e/{event.event_token}/rsvp",
        data={"name": "   ", "phone": SAM_PHONE},
    )
    assert resp.status_code == 400
    assert "required" in resp.text


async def test_start_rsvp_after_close_is_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    event.state = "closed"
    await db_session.commit()
    resp = await client.post(
        f"/e/{event.event_token}/rsvp",
        data={"name": "Sam", "phone": SAM_PHONE},
    )
    assert resp.status_code == 409
    assert "RSVPs are closed" in resp.text


# --- /r/ ---------------------------------------------------------


async def test_rsvp_page_unknown_token_404(
    client: AsyncClient,
) -> None:
    resp = await client.get("/r/deadbeefdeadbeefdead")
    assert resp.status_code == 404


async def test_pending_shows_three_buttons(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event)
    page = await client.get(f"/r/{rsvp.rsvp_token}")
    for choice in ("going", "maybe", "declined"):
        assert f'value="{choice}"' in page.text


async def test_respond_moves_state_then_no_buttons(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event)
    resp = await client.post(
        f"/r/{rsvp.rsvp_token}/respond", data={"choice": "going"}
    )
    assert resp.status_code == 303
    await db_session.refresh(rsvp)
    assert rsvp.state == "going"
    page = await client.get(f"/r/{rsvp.rsvp_token}")
    # going → attended|no_show only: no self-service back-out
    assert 'value="declined"' not in page.text
    assert "Text\n    Noah" in page.text or "Text Noah" in page.text


async def test_illegal_response_is_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="going")
    resp = await client.post(
        f"/r/{rsvp.rsvp_token}/respond",
        data={"choice": "declined"},
    )
    assert resp.status_code == 400


async def test_respond_after_close_is_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="declined")
    event.state = "closed"
    await db_session.commit()
    resp = await client.post(
        f"/r/{rsvp.rsvp_token}/respond", data={"choice": "going"}
    )
    assert resp.status_code == 409
    await db_session.refresh(rsvp)
    assert rsvp.state == "declined"


async def test_closed_rsvp_page_is_read_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="going")
    event.state = "closed"
    await db_session.commit()
    page = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "RSVPs are closed" in page.text
    assert "/respond" not in page.text
    assert "Add a card" not in page.text


async def test_paid_line_on_settled_page(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="attended")
    event.state = "settled"
    db_session.add(
        Payment(
            event_id=event.id,
            attendee_id=rsvp.attendee_id,
            attempt=1,
            state="paid",
            charged_cents=2900,
        )
    )
    await db_session.commit()
    page = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "Paid" in page.text
    assert "$29.00" in page.text


async def test_unpaid_line_on_settled_page(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="attended")
    event.state = "settled"
    db_session.add(
        Payment(
            event_id=event.id,
            attendee_id=rsvp.attendee_id,
            attempt=1,
            state="unpaid",
            state_reason="no_card",
            charge_requested_at=datetime.now(timezone.utc),
            charge_requested_cents=3000,
        )
    )
    await db_session.commit()
    page = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "Your share is" in page.text
    assert "$30.00" in page.text
    assert "payment link" in page.text


# --- card island -------------------------------------------------


async def test_card_section_for_going_without_card(
    client: AsyncClient,
    db_session: AsyncSession,
    publishable_key: None,
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="going")
    page = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "Add a card" in page.text
    assert f"/r/{rsvp.rsvp_token}/setup-intent" in page.text


async def test_card_section_hidden_for_declined(
    client: AsyncClient,
    db_session: AsyncSession,
    publishable_key: None,
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="declined")
    page = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "Add a card" not in page.text


async def test_card_on_file_replaces_island(
    client: AsyncClient,
    db_session: AsyncSession,
    publishable_key: None,
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="going")
    attendee = await db_session.get(Attendee, rsvp.attendee_id)
    assert attendee is not None
    attendee.stripe_payment_method_id = "pm_existing"
    await db_session.commit()
    page = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "card on file" in page.text
    assert "Add a card" not in page.text


async def test_missing_publishable_key_is_named(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # autouse blanking leaves the publishable key empty here
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="going")
    page = await client.get(f"/r/{rsvp.rsvp_token}")
    assert "STRIPE_PUBLISHABLE_KEY" in page.text
    assert "Add a card" not in page.text


async def test_setup_intent_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
    stripe_key: None,
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="going")
    mock_stripe.Customer.create_async = AsyncMock(
        return_value=SimpleNamespace(id="cus_new")
    )
    mock_stripe.SetupIntent.create_async = AsyncMock(
        return_value=SimpleNamespace(
            client_secret="seti_secret_123"
        )
    )
    resp = await client.post(
        f"/r/{rsvp.rsvp_token}/setup-intent"
    )
    assert resp.status_code == 200
    assert resp.json() == {"client_secret": "seti_secret_123"}
    attendee = await db_session.get(Attendee, rsvp.attendee_id)
    assert attendee is not None
    assert attendee.stripe_customer_id == "cus_new"


async def test_setup_intent_refused_for_declined(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
    stripe_key: None,
) -> None:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="declined")
    resp = await client.post(
        f"/r/{rsvp.rsvp_token}/setup-intent"
    )
    assert resp.status_code == 400
    mock_stripe.SetupIntent.create_async.assert_not_called()


async def test_setup_intent_without_secret_key_names_it(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
) -> None:
    # No stripe_key fixture: the autouse blank stands — the demo
    # machine with no .env gets told exactly what's missing.
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="going")
    resp = await client.post(
        f"/r/{rsvp.rsvp_token}/setup-intent"
    )
    assert resp.status_code == 400
    assert "STRIPE_SECRET_KEY" in resp.json()["error"]


async def test_setup_intent_stripe_error_keeps_customer(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
    stripe_key: None,
) -> None:
    """A Customer minted before the failure is committed anyway —
    the DB must know at least as much as Stripe (2026-07-13)."""
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="going")
    mock_stripe.Customer.create_async = AsyncMock(
        return_value=SimpleNamespace(id="cus_kept")
    )
    mock_stripe.SetupIntent.create_async = AsyncMock(
        side_effect=real_stripe.StripeError("stripe down")
    )
    resp = await client.post(
        f"/r/{rsvp.rsvp_token}/setup-intent"
    )
    assert resp.status_code == 502
    attendee = await db_session.get(Attendee, rsvp.attendee_id)
    assert attendee is not None
    assert attendee.stripe_customer_id == "cus_kept"


async def _going_with_customer(
    db_session: AsyncSession,
) -> tuple[Event, Rsvp, Attendee]:
    event = await _open_event(db_session)
    rsvp = await _sam_rsvp(db_session, event, state="going")
    attendee = await db_session.get(Attendee, rsvp.attendee_id)
    assert attendee is not None
    attendee.stripe_customer_id = "cus_1"
    await db_session.commit()
    return event, rsvp, attendee


async def test_finalize_persists_payment_method(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
    stripe_key: None,
) -> None:
    _, rsvp, attendee = await _going_with_customer(db_session)
    mock_stripe.SetupIntent.retrieve_async = AsyncMock(
        return_value=SimpleNamespace(
            customer="cus_1",
            status="succeeded",
            payment_method="pm_saved",
        )
    )
    page = await client.get(
        f"/r/{rsvp.rsvp_token}?setup_intent=seti_1"
    )
    assert "Card saved" in page.text
    await db_session.refresh(attendee)
    assert attendee.stripe_payment_method_id == "pm_saved"


async def test_finalize_failed_save_offers_retry(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
    stripe_key: None,
) -> None:
    """scenarios.md, card fails to save: no money was at stake —
    retry with another card or proceed cardless."""
    _, rsvp, attendee = await _going_with_customer(db_session)
    mock_stripe.SetupIntent.retrieve_async = AsyncMock(
        return_value=SimpleNamespace(
            customer="cus_1",
            status="requires_payment_method",
            payment_method=None,
        )
    )
    page = await client.get(
        f"/r/{rsvp.rsvp_token}?setup_intent=seti_1"
    )
    assert "didn't save" in page.text
    assert "tap-to-pay" in page.text
    await db_session.refresh(attendee)
    assert attendee.stripe_payment_method_id is None


async def test_finalize_foreign_intent_is_400(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_stripe: MagicMock,
    stripe_key: None,
) -> None:
    """A tampered setup_intent id must not attach someone else's
    card — record_saved_card checks ownership server-side."""
    _, rsvp, attendee = await _going_with_customer(db_session)
    mock_stripe.SetupIntent.retrieve_async = AsyncMock(
        return_value=SimpleNamespace(
            customer="cus_SOMEBODY_ELSE",
            status="succeeded",
            payment_method="pm_theirs",
        )
    )
    page = await client.get(
        f"/r/{rsvp.rsvp_token}?setup_intent=seti_1"
    )
    assert page.status_code == 400
    await db_session.refresh(attendee)
    assert attendee.stripe_payment_method_id is None
