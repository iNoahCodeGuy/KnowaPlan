"""Web layer — capability-URL routes and minimal pages.

Routes stay thin: parse the request, call a service, render a
template — services own every state write. Token lookups are
column-scoped: each route queries ONLY its own token column, so a
token can never authorize the wrong purpose (decisions.md
2026-07-13/16). Pages are server-rendered; the only browser JS is
the Stripe Payment Element island on /r/. Errors render HTML with
real status codes — the audience is someone tapping a texted
link, not an API client.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import stripe
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.events import open_rsvps
from app.models import Attendee, Event, Payment, Planner, Rsvp
from app.payments import poll_link_status

router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)

SETTLE_DEFAULTS = ("assume_all_attended", "mark_all_absent")


def _dollars(cents: int) -> str:
    # Presentation only — money stays integer cents everywhere
    # (CLAUDE.md); this filter is the ONE place digits get a "$".
    return f"${cents // 100}.{cents % 100:02d}"


templates.env.filters["dollars"] = _dollars


def parse_dollars_to_cents(raw: str) -> int:
    """Form money arrives as a dollars string; convert EXACTLY.
    Decimal, never float (CLAUDE.md): float("119.99") * 100 is
    11998.999..., and money must not depend on rounding luck.
    Sub-cent input is a typo to correct, not a value to round."""
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as err:
        raise ValueError(f"not a dollar amount: {raw!r}") from err
    if not value.is_finite():
        raise ValueError(f"not a dollar amount: {raw!r}")
    if -value.as_tuple().exponent > 2:
        raise ValueError("sub-cent amounts are not valid money")
    cents = int(value.scaleb(2))
    if cents <= 0:
        raise ValueError("total cost must be positive")
    return cents


def _parse_starts_at(raw: str) -> datetime:
    """datetime-local input ("2026-07-21T18:00") carries no zone.
    v0 stores it flagged UTC and displays it as typed — nothing in
    the demo computes with it (the settle timer is deferred); real
    timezone handling is a live-dogfood concern."""
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError as err:
        raise ValueError(f"not a date-time: {raw!r}") from err
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _not_found(request: Request) -> Response:
    # Same page and wording for every token route: a miss must not
    # reveal whether the token exists under another purpose.
    return templates.TemplateResponse(
        request, "not_found.html", {}, status_code=404
    )


def _cannot(request: Request, message: str) -> Response:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": message},
        status_code=400,
    )


async def _event_by_admin_token(
    session: AsyncSession, token: str
) -> Event | None:
    return (
        await session.execute(
            select(Event).where(Event.admin_token == token)
        )
    ).scalar_one_or_none()


@router.get("/")
async def create_event_form(request: Request) -> Response:
    return templates.TemplateResponse(
        request, "create_event.html", {"error": None, "form": {}}
    )


@router.post("/events")
async def create_event(
    request: Request,
    session: AsyncSession = Depends(get_session),
    planner_name: str = Form(...),
    planner_phone: str = Form(...),
    title: str = Form(...),
    starts_at: str = Form(...),
    total_cost_dollars: str = Form(...),
    goal_attendance: int = Form(...),
    settle_default: str = Form(...),
) -> Response:
    form = {
        "planner_name": planner_name,
        "planner_phone": planner_phone,
        "title": title,
        "starts_at": starts_at,
        "total_cost_dollars": total_cost_dollars,
        "goal_attendance": str(goal_attendance),
        "settle_default": settle_default,
    }

    def fail(message: str) -> Response:
        return templates.TemplateResponse(
            request,
            "create_event.html",
            {"error": message, "form": form},
            status_code=400,
        )

    planner_name = planner_name.strip()
    planner_phone = planner_phone.strip()
    title = title.strip()
    if not (planner_name and planner_phone and title):
        return fail("name, phone and title are required")
    try:
        total_cents = parse_dollars_to_cents(total_cost_dollars)
        starts = _parse_starts_at(starts_at)
    except ValueError as err:
        return fail(str(err))
    if goal_attendance < 1:
        return fail("goal attendance must be at least 1")
    if settle_default not in SETTLE_DEFAULTS:
        return fail("unknown settle default")
    account_id = get_settings().test_planner_account_id
    if not account_id:
        # The demo's one piece of required config fails at the
        # FIRST step, loudly — not at settlement.
        return fail(
            "TEST_PLANNER_ACCOUNT_ID is not configured — set it "
            "in .env before creating events"
        )
    planner = (
        await session.execute(
            select(Planner).where(Planner.phone == planner_phone)
        )
    ).scalar_one_or_none()
    if planner is None:
        planner = Planner(
            name=planner_name,
            phone=planner_phone,
            stripe_account_id=account_id,
        )
        session.add(planner)
        await session.flush()
    event = Event(
        planner_id=planner.id,
        title=title,
        starts_at=starts,
        total_cost_cents=total_cents,
        goal_attendance=goal_attendance,
        # The quoted estimate, snapshotted at creation (decisions.md
        # 2026-07-16). Floor matches the split rule — ceil was the
        # hold model's never-under-authorize, and there is no hold.
        estimated_share_cents=total_cents // goal_attendance,
        settle_default=settle_default,
    )
    session.add(event)
    await session.commit()
    return RedirectResponse(
        f"/admin/{event.admin_token}", status_code=303
    )


@router.post("/admin/{token}/open")
async def open_event(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    event = await _event_by_admin_token(session, token)
    if event is None:
        return _not_found(request)
    try:
        await open_rsvps(session, event)
    except ValueError:
        return _cannot(
            request,
            f"RSVPs can't open from state {event.state!r}.",
        )
    return RedirectResponse(f"/admin/{token}", status_code=303)


@router.get("/admin/{token}")
async def admin_page(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    event = await _event_by_admin_token(session, token)
    if event is None:
        return _not_found(request)
    planner = await session.get(Planner, event.planner_id)
    rows = (
        await session.execute(
            select(Rsvp, Attendee)
            .join(Attendee, Rsvp.attendee_id == Attendee.id)
            .where(Rsvp.event_id == event.id)
            .order_by(Attendee.name)
        )
    ).all()
    payments = {
        p.attendee_id: p
        for p in (
            await session.execute(
                select(Payment).where(
                    Payment.event_id == event.id
                )
            )
        ).scalars()
    }
    # No-webhook reconciliation (decisions.md 2026-07-15): nudge
    # every outstanding link once per roster view. One row's Stripe
    # hiccup must not take down the planner's page — that row just
    # reads "status unknown" until the next load.
    poll_failed: set[int] = set()
    for payment in payments.values():
        if (
            payment.state == "unpaid"
            and payment.stripe_checkout_session_id is not None
        ):
            try:
                await poll_link_status(payment)
                await session.commit()
            except stripe.StripeError:
                poll_failed.add(payment.attendee_id)
    share_link = (
        str(request.base_url).rstrip("/")
        + f"/e/{event.event_token}"
    )
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "event": event,
            "planner": planner,
            "rows": rows,
            "payments": payments,
            "poll_failed": poll_failed,
            "share_link": share_link,
        },
    )
