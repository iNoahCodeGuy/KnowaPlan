"""Web layer: event creation + admin roster (app/web.py).

Pins: exact Decimal money parsing (never float), the loud refusal
when the demo's one required config is missing, capability-token
lookups (miss = uniform 404), draft→open, roster rendering, and
per-row containment of the roster's link polling.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import stripe as real_stripe
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Payment, Planner, Rsvp
from app.rsvps import get_or_create_rsvp
from app.web import parse_dollars_to_cents

PLANNER_PHONE = "+15550000001"
SAM_PHONE = "+15550000002"


@pytest.fixture
def planner_account(monkeypatch: pytest.MonkeyPatch) -> str:
    """The demo's required config; the autouse blanking fixture
    ran first, so these win for tests that opt in."""
    monkeypatch.setenv("PLANNER_ACCOUNT_ID", "acct_demo")
    monkeypatch.setenv("CREATE_PASSWORD", "letmein")
    return "acct_demo"


def _form(**overrides: str) -> dict[str, str]:
    form = {
        "planner_name": "Noah",
        "planner_phone": PLANNER_PHONE,
        "title": "Tuesday pickleball",
        "starts_at": "2026-07-21T18:00",
        "total_cost_dollars": "120",
        "goal_attendance": "4",
        "settle_default": "assume_all_attended",
        "create_password": "letmein",
    }
    form.update(overrides)
    return form


async def _created_event(
    client: AsyncClient,
    db_session: AsyncSession,
    **overrides: str,
) -> Event:
    resp = await client.post("/events", data=_form(**overrides))
    assert resp.status_code == 303
    token = resp.headers["location"].removeprefix("/admin/")
    event = (
        await db_session.execute(
            select(Event).where(Event.admin_token == token)
        )
    ).scalar_one()
    return event


def test_parse_dollars_is_exact() -> None:
    # 119.99 is the float trap: float("119.99")*100 = 11998.999...
    assert parse_dollars_to_cents("119.99") == 11999
    assert parse_dollars_to_cents("120") == 12000
    assert parse_dollars_to_cents(" 0.01 ") == 1


@pytest.mark.parametrize(
    "raw", ["abc", "12.345", "0", "-5", "NaN", "Infinity", ""]
)
def test_parse_dollars_refuses_junk(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_dollars_to_cents(raw)


async def test_create_form_renders(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'name="total_cost_dollars"' in resp.text


async def test_create_event_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
    planner_account: str,
) -> None:
    event = await _created_event(client, db_session)
    assert event.state == "draft"
    assert event.total_cost_cents == 12000
    assert event.estimated_share_cents == 3000  # floor(12000/4)
    planner = await db_session.get(Planner, event.planner_id)
    assert planner is not None
    assert planner.stripe_account_id == planner_account
    admin = await client.get(f"/admin/{event.admin_token}")
    assert admin.status_code == 200
    assert "Tuesday pickleball" in admin.text
    assert f"/e/{event.event_token}" in admin.text


async def test_decimal_money_survives_the_wire(
    client: AsyncClient,
    db_session: AsyncSession,
    planner_account: str,
) -> None:
    event = await _created_event(
        client, db_session, total_cost_dollars="119.99"
    )
    assert event.total_cost_cents == 11999


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total_cost_dollars", "abc"),
        ("total_cost_dollars", "12.345"),
        ("total_cost_dollars", "0"),
        ("goal_attendance", "0"),
        ("settle_default", "shrug"),
        ("starts_at", "someday"),
    ],
)
async def test_bad_form_input_is_a_400(
    client: AsyncClient,
    planner_account: str,
    field: str,
    value: str,
) -> None:
    resp = await client.post(
        "/events", data=_form(**{field: value})
    )
    assert resp.status_code == 400
    assert "error" in resp.text


async def test_unset_create_password_fails_closed(
    client: AsyncClient,
) -> None:
    # No fixture: the autouse blanks stand in for a host with no
    # CREATE_PASSWORD — the public create page must stay locked,
    # not open (real money routes through created events).
    resp = await client.post("/events", data=_form())
    assert resp.status_code == 400
    assert "CREATE_PASSWORD" in resp.text


async def test_wrong_create_password_refused(
    client: AsyncClient, planner_account: str
) -> None:
    resp = await client.post(
        "/events", data=_form(create_password="nope")
    )
    assert resp.status_code == 400
    assert "password" in resp.text


async def test_missing_account_config_fails_loudly(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Gate passes, account id still blank: creation must refuse
    # at the FIRST step, not defer the surprise to settlement.
    monkeypatch.setenv("CREATE_PASSWORD", "letmein")
    resp = await client.post("/events", data=_form())
    assert resp.status_code == 400
    assert "PLANNER_ACCOUNT_ID" in resp.text


async def test_password_never_echoed_on_failed_form(
    client: AsyncClient, planner_account: str
) -> None:
    resp = await client.post(
        "/events", data=_form(total_cost_dollars="abc")
    )
    assert resp.status_code == 400
    assert "letmein" not in resp.text


async def test_planner_reused_by_phone(
    client: AsyncClient,
    db_session: AsyncSession,
    planner_account: str,
) -> None:
    await _created_event(client, db_session)
    await _created_event(client, db_session, title="Thursday run")
    planners = (
        (await db_session.execute(select(Planner))).scalars().all()
    )
    events = (
        (await db_session.execute(select(Event))).scalars().all()
    )
    assert len(planners) == 1
    assert len(events) == 2


async def test_unknown_admin_token_is_html_404(
    client: AsyncClient,
) -> None:
    resp = await client.get("/admin/deadbeefdeadbeefdead")
    assert resp.status_code == 404
    assert "doesn't point anywhere" in resp.text


async def test_open_rsvps_button(
    client: AsyncClient,
    db_session: AsyncSession,
    planner_account: str,
) -> None:
    event = await _created_event(client, db_session)
    resp = await client.post(f"/admin/{event.admin_token}/open")
    assert resp.status_code == 303
    await db_session.refresh(event)
    assert event.state == "open"
    again = await client.post(f"/admin/{event.admin_token}/open")
    assert again.status_code == 400  # open → open is illegal


async def test_roster_rows_and_card_badge(
    client: AsyncClient,
    db_session: AsyncSession,
    planner_account: str,
) -> None:
    event = await _created_event(client, db_session)
    event.state = "open"
    await db_session.commit()
    rsvp = await get_or_create_rsvp(
        db_session, event, "Sam", SAM_PHONE
    )
    page = await client.get(f"/admin/{event.admin_token}")
    assert "Sam" in page.text
    assert "pending" in page.text
    assert "no card" in page.text
    attendee = await db_session.get(Attendee, rsvp.attendee_id)
    assert attendee is not None
    attendee.stripe_payment_method_id = "pm_test"
    await db_session.commit()
    page = await client.get(f"/admin/{event.admin_token}")
    assert "card on file" in page.text


async def _unpaid_row(
    db_session: AsyncSession, event: Event
) -> Payment:
    attendee = Attendee(name="Sam", phone=SAM_PHONE)
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
    payment = Payment(
        event_id=event.id,
        attendee_id=attendee.id,
        attempt=1,
        state="unpaid",
        state_reason="no_card",
        stripe_checkout_session_id="cs_test_1",
        charge_requested_at=datetime.now(timezone.utc),
        charge_requested_cents=3000,
    )
    db_session.add(payment)
    await db_session.commit()
    return payment


async def test_roster_poll_moves_paid_link_to_paid(
    client: AsyncClient,
    db_session: AsyncSession,
    planner_account: str,
    mock_stripe: MagicMock,
) -> None:
    event = await _created_event(client, db_session)
    payment = await _unpaid_row(db_session, event)
    mock_stripe.checkout.Session.retrieve_async = AsyncMock(
        return_value=SimpleNamespace(
            payment_status="paid",
            amount_total=3000,
            payment_intent="pi_link_1",
            status="complete",
        )
    )
    page = await client.get(f"/admin/{event.admin_token}")
    assert page.status_code == 200
    assert "paid" in page.text
    await db_session.refresh(payment)
    assert payment.state == "paid"
    assert payment.charged_cents == 3000


async def test_roster_poll_error_is_contained(
    client: AsyncClient,
    db_session: AsyncSession,
    planner_account: str,
    mock_stripe: MagicMock,
) -> None:
    event = await _created_event(client, db_session)
    payment = await _unpaid_row(db_session, event)
    mock_stripe.checkout.Session.retrieve_async = AsyncMock(
        side_effect=real_stripe.StripeError("stripe hiccup")
    )
    page = await client.get(f"/admin/{event.admin_token}")
    assert page.status_code == 200  # the page never 500s over it
    assert "status unknown" in page.text
    await db_session.refresh(payment)
    assert payment.state == "unpaid"  # unchanged, retried next load


async def test_paid_page_renders(client: AsyncClient) -> None:
    """Checkout's success_url target: static, tokenless, safe to
    land on from any payment."""
    resp = await client.get("/paid")
    assert resp.status_code == 200
    assert "Payment received" in resp.text


@pytest.mark.xfail(
    strict=True,
    reason="gross_up step: creation stores the grossed estimate "
    "(shaping call 3, confirmed 2026-07-18)",
)
async def test_create_event_estimate_is_grossed(
    client: AsyncClient,
    db_session: AsyncSession,
    planner_account: str,
) -> None:
    """The number quoted at RSVP is the number that hits the card:
    estimated_share_cents stores gross_up(total // goal) — $120 at
    goal 4 quotes $31.21, not $30.00. When this wires, the older
    == 3000 assertion above flips to 3121 in the same edit."""
    event = await _created_event(client, db_session)
    assert event.estimated_share_cents == 3121
