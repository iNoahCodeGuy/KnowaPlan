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
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import stripe
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.events import cancel_event, open_rsvps
from app.models import Attendee, Event, Payment, Planner, Rsvp
from app.payments import (
    CardSaveFailed,
    create_payment_link,
    create_setup_intent,
    poll_link_status,
    record_saved_card,
)
from app.rsvps import (
    EventNotOpen,
    allowed_choices,
    get_or_create_rsvp,
    respond,
)
from app.settlement import (
    close_rsvps,
    mark_attendance,
    retry_dangling,
    settle_event,
)

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


def _success_url(request: Request) -> str:
    # Stripe requires an absolute success_url on every Checkout
    # Session (decisions.md 2026-07-16). Built from the request host
    # — the same source share links use — so the proxy headers that
    # make /e/ links right on a deploy make this right too.
    return str(request.base_url).rstrip("/") + "/paid"


async def _event_by_admin_token(
    session: AsyncSession, token: str
) -> Event | None:
    return (
        await session.execute(
            select(Event).where(Event.admin_token == token)
        )
    ).scalar_one_or_none()


async def _event_by_event_token(
    session: AsyncSession, token: str
) -> Event | None:
    return (
        await session.execute(
            select(Event).where(Event.event_token == token)
        )
    ).scalar_one_or_none()


async def _rsvp_by_token(
    session: AsyncSession, token: str
) -> Rsvp | None:
    return (
        await session.execute(
            select(Rsvp).where(Rsvp.rsvp_token == token)
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
    create_password: str = Form(""),
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
        # `form` never carries the password — a failed re-render
        # must not echo it back into the page.
        return templates.TemplateResponse(
            request,
            "create_event.html",
            {"error": message, "form": form},
            status_code=400,
        )

    settings = get_settings()
    # Gate FIRST: on a public host, creating an event routes real
    # money into the planner's Stripe — strangers must not mint
    # events. Unset password = creation refused (fail closed).
    if not settings.create_password:
        return fail(
            "CREATE_PASSWORD is not configured — set it in .env; "
            "event creation stays locked without it"
        )
    if not secrets.compare_digest(
        create_password.encode(),
        settings.create_password.encode(),
    ):
        return fail("wrong create password")
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
    account_id = settings.planner_account_id
    if not account_id:
        # Required config fails at the FIRST step, loudly — not
        # at settlement.
        return fail(
            "PLANNER_ACCOUNT_ID is not configured — set it in "
            ".env before creating events"
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


def _render_event(
    request: Request,
    event: Event,
    planner: Planner | None,
    error: str | None = None,
    form: dict[str, str] | None = None,
    status_code: int = 200,
) -> Response:
    return templates.TemplateResponse(
        request,
        "event.html",
        {
            "event": event,
            "planner": planner,
            "error": error,
            "form": form or {},
        },
        status_code=status_code,
    )


@router.get("/e/{token}")
async def event_page(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    event = await _event_by_event_token(session, token)
    if event is None:
        return _not_found(request)
    planner = await session.get(Planner, event.planner_id)
    return _render_event(request, event, planner)


@router.post("/e/{token}/rsvp")
async def start_rsvp(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
    name: str = Form(...),
    phone: str = Form(...),
) -> Response:
    event = await _event_by_event_token(session, token)
    if event is None:
        return _not_found(request)
    planner = await session.get(Planner, event.planner_id)
    try:
        rsvp = await get_or_create_rsvp(
            session, event, name, phone
        )
    except EventNotOpen:
        # The form was honest when rendered; the event changed
        # underneath it — Conflict, and the stale page says why.
        return _render_event(
            request, event, planner, status_code=409
        )
    except ValueError as err:
        return _render_event(
            request,
            event,
            planner,
            error=str(err),
            form={"name": name, "phone": phone},
            status_code=400,
        )
    return RedirectResponse(
        f"/r/{rsvp.rsvp_token}", status_code=303
    )


@router.get("/r/{token}")
async def rsvp_page(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
    setup_intent: str | None = None,
) -> Response:
    rsvp = await _rsvp_by_token(session, token)
    if rsvp is None:
        return _not_found(request)
    event = await session.get(Event, rsvp.event_id)
    attendee = await session.get(Attendee, rsvp.attendee_id)
    if event is None or attendee is None:
        return _not_found(request)
    planner = await session.get(Planner, event.planner_id)
    card_banner: str | None = None
    card_error: str | None = None
    if (
        setup_intent is not None
        and attendee.stripe_customer_id is not None
    ):
        # Finalize a card save — the single server path for both
        # the 3DS-redirect return and the island's own navigation.
        # record_saved_card re-retrieves the intent and refuses
        # foreign ownership; the browser is never trusted.
        try:
            await record_saved_card(attendee, setup_intent)
            await session.commit()
            card_banner = "saved"
        except CardSaveFailed as failed:
            card_banner = "failed"
            card_error = str(failed)
        except ValueError:
            return _cannot(
                request,
                "That card confirmation doesn't belong to this "
                "link.",
            )
        except stripe.StripeError:
            card_banner = "unverified"
    payment = (
        (
            await session.execute(
                select(Payment)
                .where(
                    Payment.event_id == event.id,
                    Payment.attendee_id == attendee.id,
                )
                .order_by(Payment.attempt.desc())
            )
        )
        .scalars()
        .first()
    )
    choices = (
        allowed_choices(rsvp) if event.state == "open" else ()
    )
    show_card_section = (
        event.state == "open"
        and rsvp.state in ("going", "maybe")
    )
    return templates.TemplateResponse(
        request,
        "rsvp.html",
        {
            "event": event,
            "rsvp": rsvp,
            "attendee": attendee,
            "planner": planner,
            "payment": payment,
            "choices": choices,
            "show_card_section": show_card_section,
            "card_banner": card_banner,
            "card_error": card_error,
            "publishable_key": (
                get_settings().stripe_publishable_key
            ),
        },
    )


@router.post("/r/{token}/respond")
async def respond_rsvp(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
    choice: str = Form(...),
) -> Response:
    rsvp = await _rsvp_by_token(session, token)
    if rsvp is None:
        return _not_found(request)
    event = await session.get(Event, rsvp.event_id)
    if event is None:
        return _not_found(request)
    try:
        await respond(session, rsvp, event, choice)
    except EventNotOpen:
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "message": "RSVPs for this event are closed — "
                "answers can't change now.",
            },
            status_code=409,
        )
    except ValueError as err:
        return _cannot(request, str(err))
    return RedirectResponse(f"/r/{token}", status_code=303)


@router.post("/r/{token}/setup-intent")
async def setup_intent_endpoint(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """The card island's fetch: mint a SetupIntent and hand back
    its client_secret. No money moves (a save, not a charge)."""
    rsvp = await _rsvp_by_token(session, token)
    if rsvp is None:
        return JSONResponse(
            {"error": "unknown link"}, status_code=404
        )
    event = await session.get(Event, rsvp.event_id)
    if (
        event is None
        or event.state != "open"
        or rsvp.state not in ("going", "maybe")
    ):
        # Card saving is for going/maybe answers on an open event
        # (decisions.md 2026-07-15).
        return JSONResponse(
            {
                "error": "card saving is only available while "
                "the event is open and you're going or maybe"
            },
            status_code=400,
        )
    if not get_settings().stripe_secret_key:
        return JSONResponse(
            {"error": "STRIPE_SECRET_KEY is not configured"},
            status_code=400,
        )
    attendee = await session.get(Attendee, rsvp.attendee_id)
    if attendee is None:
        return JSONResponse(
            {"error": "unknown link"}, status_code=404
        )
    try:
        secret = await create_setup_intent(attendee)
    except stripe.StripeError:
        # Keep any Customer id minted before the failure — the DB
        # must know at least as much as Stripe (decisions.md
        # 2026-07-13).
        await session.commit()
        return JSONResponse(
            {"error": "card setup is unavailable right now"},
            status_code=502,
        )
    await session.commit()  # persist stripe_customer_id
    return JSONResponse({"client_secret": secret})


def _settle_math(
    event: Event,
    rows: list[tuple[Rsvp, Attendee]],
    planner: Planner,
) -> dict[str, object]:
    """Read-only mirror of settle_event's selection rules
    (app/settlement.py) — participants, share, and the warnings
    the preview owes the planner. If settle_event's rules ever
    change, change this WITH it; the preview must never promise a
    different split than the settle performs."""
    assume = event.settle_default == "assume_all_attended"
    participants: list[Attendee] = []
    unmarked = 0
    maybes = 0
    for rsvp, attendee in rows:
        undecided = (
            rsvp.state == "going"
            and rsvp.attendance == "unconfirmed"
        )
        if rsvp.attendance == "present":
            participants.append(attendee)
        elif undecided:
            unmarked += 1
            if assume:
                participants.append(attendee)
        elif rsvp.state == "maybe":
            maybes += 1
    divisor = len(participants)
    share = event.total_cost_cents // divisor if divisor else 0
    planner_playing = any(
        attendee.id == planner.attendee_id
        for attendee in participants
    )
    chargeable = divisor - (1 if planner_playing else 0)
    over = share > event.estimated_share_cents
    return {
        "participants": divisor,
        "share": share,
        "chargeable": chargeable,
        "unmarked": unmarked,
        "maybes": maybes,
        "planner_playing": planner_playing,
        "over_estimate": over,
        "capped_shortfall": (
            (share - event.estimated_share_cents) * chargeable
            if over
            else 0
        ),
        "assume": assume,
    }


async def _event_rows(
    session: AsyncSession, event: Event
) -> list[tuple[Rsvp, Attendee]]:
    return list(
        (
            await session.execute(
                select(Rsvp, Attendee)
                .join(Attendee, Rsvp.attendee_id == Attendee.id)
                .where(Rsvp.event_id == event.id)
                .order_by(Attendee.name)
            )
        ).all()
    )


@router.post("/admin/{token}/close")
async def close_event_route(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    event = await _event_by_admin_token(session, token)
    if event is None:
        return _not_found(request)
    try:
        await close_rsvps(session, event)
    except ValueError:
        return _cannot(
            request,
            f"RSVPs can't close from state {event.state!r}.",
        )
    return RedirectResponse(f"/admin/{token}", status_code=303)


@router.post("/admin/{token}/attendance")
async def mark_attendance_route(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
    rsvp_id: int = Form(...),
    present: str = Form(...),
) -> Response:
    event = await _event_by_admin_token(session, token)
    if event is None:
        return _not_found(request)
    rsvp = await session.get(Rsvp, rsvp_id)
    if rsvp is None or rsvp.event_id != event.id:
        # An admin link must never reach into another event.
        return _not_found(request)
    if present not in ("yes", "no"):
        return _cannot(request, "present must be yes or no")
    if event.state not in ("open", "closed"):
        return _cannot(
            request,
            f"attendance can't change once the event is "
            f"{event.state} (the 72h re-mark ships with refunds)",
        )
    if event.state == "open":
        # Marking begins => RSVPs close (state_machines.md).
        await close_rsvps(session, event)
    try:
        await mark_attendance(session, rsvp, present == "yes")
    except ValueError:
        return _cannot(
            request,
            "only a `going` answer can be marked — a maybe has "
            "to tap Going on their own link first, and a marked "
            "row stays marked (re-marking ships with refunds)",
        )
    return RedirectResponse(f"/admin/{token}", status_code=303)


@router.get("/admin/{token}/cancel")
async def cancel_confirm(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    event = await _event_by_admin_token(session, token)
    if event is None:
        return _not_found(request)
    return templates.TemplateResponse(
        request, "cancel_confirm.html", {"event": event}
    )


@router.post("/admin/{token}/cancel")
async def cancel_route(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    event = await _event_by_admin_token(session, token)
    if event is None:
        return _not_found(request)
    try:
        await cancel_event(session, event)
    except ValueError as err:
        return _cannot(request, str(err))
    return RedirectResponse(f"/admin/{token}", status_code=303)


@router.post("/admin/{token}/retry/{payment_id}")
async def retry_route(
    request: Request,
    token: str,
    payment_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    event = await _event_by_admin_token(session, token)
    if event is None:
        return _not_found(request)
    payment = await session.get(Payment, payment_id)
    if payment is None or payment.event_id != event.id:
        return _not_found(request)
    attendee = await session.get(Attendee, payment.attendee_id)
    planner = await session.get(Planner, event.planner_id)
    if attendee is None or planner is None:
        return _not_found(request)
    try:
        outcome = await retry_dangling(
            session,
            payment,
            attendee,
            planner,
            success_url=_success_url(request),
        )
    except ValueError as err:
        return _cannot(request, str(err))
    except (stripe.StripeError, RuntimeError):
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "message": "Stripe is unreachable — the row stays "
                "flagged, and retrying again is safe (same "
                "idempotency key, decisions.md 2026-07-13).",
            },
            status_code=502,
        )
    return templates.TemplateResponse(
        request,
        "link_result.html",
        {
            "event": event,
            "attendee": attendee,
            "outcome": outcome.result,
            "link_url": outcome.link_url,
            "amount_cents": payment.charge_requested_cents,
            "token": token,
        },
    )


@router.post("/admin/{token}/link/{payment_id}")
async def fresh_link_route(
    request: Request,
    token: str,
    payment_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    event = await _event_by_admin_token(session, token)
    if event is None:
        return _not_found(request)
    payment = await session.get(Payment, payment_id)
    if payment is None or payment.event_id != event.id:
        return _not_found(request)
    if payment.charge_requested_cents is None:
        return _cannot(request, "this row has no stamped amount")
    attendee = await session.get(Attendee, payment.attendee_id)
    planner = await session.get(Planner, event.planner_id)
    if attendee is None or planner is None:
        return _not_found(request)
    try:
        # Always the STAMPED amount — a re-mint is the same debt,
        # never a recompute (decisions.md 2026-07-16).
        url = await create_payment_link(
            payment,
            planner,
            payment.charge_requested_cents,
            success_url=_success_url(request),
        )
    except ValueError as err:
        # e.g. the old link already collected — the next roster
        # load's poll reconciles it.
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": f"{err} — reload the roster."},
            status_code=409,
        )
    except stripe.StripeError:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": "Stripe is unreachable — try again."},
            status_code=502,
        )
    await session.commit()  # the row now points at the new session
    return templates.TemplateResponse(
        request,
        "link_result.html",
        {
            "event": event,
            "attendee": attendee,
            "outcome": "unpaid",
            "link_url": url,
            "amount_cents": payment.charge_requested_cents,
            "token": token,
        },
    )


@router.get("/admin/{token}/settle")
async def settle_preview(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    event = await _event_by_admin_token(session, token)
    if event is None:
        return _not_found(request)
    if event.state not in ("open", "closed"):
        return _cannot(
            request,
            f"can't settle an event that is {event.state}",
        )
    planner = await session.get(Planner, event.planner_id)
    if planner is None:
        return _not_found(request)
    rows = await _event_rows(session, event)
    math = _settle_math(event, rows, planner)
    return templates.TemplateResponse(
        request,
        "settle_preview.html",
        {"event": event, "planner": planner, **math},
    )


@router.post("/admin/{token}/settle")
async def settle_route(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
    mode: str = Form(...),
) -> Response:
    event = await _event_by_admin_token(session, token)
    if event is None:
        return _not_found(request)
    if mode not in ("actual", "cap"):
        # Absorbing is an ACTIVE choice; anything ambiguous is
        # refused rather than defaulted (decisions.md 2026-07-15).
        return _cannot(request, "mode must be actual or cap")
    planner = await session.get(Planner, event.planner_id)
    if planner is None:
        return _not_found(request)
    try:
        report = await settle_event(
            session,
            event,
            planner,
            success_url=_success_url(request),
            cap_at_estimate=(mode == "cap"),
        )
    except ValueError as err:
        return _cannot(request, str(err))
    rows = await _event_rows(session, event)
    attendees_by_id = {a.id: a for _, a in rows}
    payments_by_attendee = {
        p.attendee_id: p
        for p in (
            await session.execute(
                select(Payment).where(
                    Payment.event_id == event.id
                )
            )
        ).scalars()
    }
    return templates.TemplateResponse(
        request,
        "settle_report.html",
        {
            "event": event,
            "report": report,
            "attendees_by_id": attendees_by_id,
            "payments_by_attendee": payments_by_attendee,
        },
    )


@router.get("/paid")
async def paid_page(request: Request) -> Response:
    # Checkout's success_url lands here (decisions.md 2026-07-16).
    # Static on purpose: no token, nothing to leak, nothing to poll
    # — the roster's on-load poll is what records the payment.
    return templates.TemplateResponse(request, "paid.html", {})
