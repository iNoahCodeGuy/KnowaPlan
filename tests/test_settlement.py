"""Settlement service tests — real DB session (in-memory SQLite,
conftest db_session), mocked Stripe where money is involved. The
transactional claims (one commit per action; record-first ordering
in later steps) are pinned against real commits, and persistence is
verified by refreshing from the DB, never by trusting the object.
"""
from datetime import datetime, timezone
from itertools import count
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Payment, Planner, Rsvp
from app.settlement import (
    close_rsvps,
    mark_attendance,
    settle_event,
)

STARTS_AT = datetime(2026, 7, 18, 18, 0, tzinfo=timezone.utc)


async def _seed_event(
    session: AsyncSession, **event_overrides: Any
) -> Event:
    """A minimal open event: $120 court, goal 4, estimate $30."""
    fields: dict[str, Any] = {
        "title": "Pickleball",
        "starts_at": STARTS_AT,
        "total_cost_cents": 12_000,
        "goal_attendance": 4,
        "estimated_share_cents": 3_000,
        "state": "open",
    }
    fields.update(event_overrides)
    planner = Planner(
        name="Pat Planner",
        phone="+15550000002",
        stripe_account_id="acct_9",
    )
    session.add(planner)
    await session.flush()
    event = Event(planner_id=planner.id, **fields)
    session.add(event)
    await session.commit()
    return event


async def _seed_rsvp(
    session: AsyncSession,
    event: Event,
    *,
    phone: str = "+15550000001",
    state: str = "going",
    attendance: str = "unconfirmed",
    **attendee_overrides: Any,
) -> Rsvp:
    attendee = Attendee(
        name="Ana Attendee", phone=phone, **attendee_overrides
    )
    session.add(attendee)
    await session.flush()
    rsvp = Rsvp(
        event_id=event.id,
        attendee_id=attendee.id,
        state=state,
        attendance=attendance,
    )
    session.add(rsvp)
    await session.commit()
    return rsvp


async def _seed_present_carded(
    session: AsyncSession, event: Event, phone: str
) -> Rsvp:
    """A friend already marked present, card on file."""
    return await _seed_rsvp(
        session,
        event,
        phone=phone,
        state="attended",
        attendance="present",
        stripe_customer_id=f"cus_{phone[-1]}",
        stripe_payment_method_id=f"pm_{phone[-1]}",
    )


async def _planner_plays(
    session: AsyncSession, event: Event
) -> Rsvp:
    """The planner participates: ordinary Attendee + Rsvp row,
    linked via Planner.attendee_id (decisions.md 2026-07-16)."""
    planner = await session.get(Planner, event.planner_id)
    assert planner is not None
    attendee = Attendee(name=planner.name, phone=planner.phone)
    session.add(attendee)
    await session.flush()
    planner.attendee_id = attendee.id
    rsvp = Rsvp(
        event_id=event.id,
        attendee_id=attendee.id,
        state="attended",
        attendance="present",
    )
    session.add(rsvp)
    await session.commit()
    return rsvp


def _succeeding_pi() -> AsyncMock:
    """Distinct PI ids per call — stripe_payment_intent_id is
    unique, so a shared return_value would collide on commit."""
    ids = count(1)
    return AsyncMock(
        side_effect=lambda **kw: SimpleNamespace(
            id=f"pi_{next(ids)}", status="succeeded"
        )
    )


async def _payments(session: AsyncSession) -> list[Payment]:
    result = await session.execute(select(Payment))
    return list(result.scalars().all())


class TestMarkAttendance:
    async def test_present_marks_both_machines(
        self, db_session: AsyncSession
    ) -> None:
        """One fact, two machines: going -> attended AND
        unconfirmed -> present land together, persisted."""
        event = await _seed_event(db_session)
        rsvp = await _seed_rsvp(db_session, event)

        result = await mark_attendance(db_session, rsvp, True)

        await db_session.refresh(result)
        assert result.state == "attended"
        assert result.attendance == "present"

    async def test_absent_marks_both_machines(
        self, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        rsvp = await _seed_rsvp(db_session, event)

        result = await mark_attendance(db_session, rsvp, False)

        await db_session.refresh(result)
        assert result.state == "no_show"
        assert result.attendance == "absent"

    @pytest.mark.parametrize(
        "state", ["pending", "maybe", "declined"]
    )
    async def test_non_going_rows_cannot_be_marked(
        self, db_session: AsyncSession, state: str
    ) -> None:
        """v0 marks people who said going; walk-ins are deferred.
        Neither field may mutate on the refusal."""
        event = await _seed_event(db_session)
        rsvp = await _seed_rsvp(db_session, event, state=state)

        with pytest.raises(ValueError):
            await mark_attendance(db_session, rsvp, True)
        assert rsvp.state == state
        assert rsvp.attendance == "unconfirmed"

    async def test_remarking_terminal_rsvp_raises(
        self, db_session: AsyncSession
    ) -> None:
        """attended/present are terminal by table law; post-settle
        re-marking ships with refunds, not before."""
        event = await _seed_event(db_session)
        rsvp = await _seed_rsvp(
            db_session,
            event,
            state="attended",
            attendance="present",
        )

        with pytest.raises(ValueError):
            await mark_attendance(db_session, rsvp, False)
        assert rsvp.state == "attended"
        assert rsvp.attendance == "present"


class TestCloseRsvps:
    async def test_open_event_closes(
        self, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)

        await close_rsvps(db_session, event)

        await db_session.refresh(event)
        assert event.state == "closed"

    @pytest.mark.parametrize(
        "state", ["draft", "closed", "settled", "cancelled"]
    )
    async def test_close_from_wrong_state_raises(
        self, db_session: AsyncSession, state: str
    ) -> None:
        event = await _seed_event(db_session, state=state)

        with pytest.raises(ValueError):
            await close_rsvps(db_session, event)
        assert event.state == state


class TestSettleEvent:
    async def test_happy_path_charges_everyone_but_planner(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """$120, planner + 3 carded friends present: divisor 4,
        share $30, three paid rows — and NO Payment row for the
        planner (a divisor, never a charge)."""
        event = await _seed_event(db_session)
        await _planner_plays(db_session, event)
        for n in (1, 3, 4):
            await _seed_present_carded(
                db_session, event, f"+1555000000{n}"
            )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        assert report.share_cents == 3000
        assert report.charge_cents == 3000
        assert report.shortfall_cents == 0
        assert len(report.outcomes) == 3
        assert all(o.result == "paid" for o in report.outcomes)
        payments = await _payments(db_session)
        assert len(payments) == 3
        assert all(
            p.state == "paid" and p.charged_cents == 3000
            for p in payments
        )
        assert planner.attendee_id not in {
            p.attendee_id for p in payments
        }
        await db_session.refresh(event)
        assert event.state == "settled"
        assert event.settled_at is not None

    async def test_floor_split_remainder_absorbed(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """$100 ÷ 3 = 3333 each; the leftover cent is the
        planner's, never redistributed."""
        event = await _seed_event(
            db_session, total_cost_cents=10_000
        )
        for n in (1, 3, 4):
            await _seed_present_carded(
                db_session, event, f"+1555000000{n}"
            )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        assert report.share_cents == 3333
        payments = await _payments(db_session)
        assert [p.charged_cents for p in payments] == [3333] * 3

    async def test_cardless_lands_unpaid_with_link(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """No card -> unpaid + reason + tap-to-pay link minted and
        stored; the carded friend still pays automatically."""
        event = await _seed_event(db_session)
        await _seed_present_carded(db_session, event, "+15550000001")
        await _seed_rsvp(
            db_session,
            event,
            phone="+15550000003",
            state="attended",
            attendance="present",
        )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()
        mock_stripe.checkout.Session.create_async = AsyncMock(
            return_value=SimpleNamespace(
                id="cs_1",
                url="https://checkout.stripe.com/c/pay/cs_1",
            )
        )

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        by_result = {o.result: o for o in report.outcomes}
        assert set(by_result) == {"paid", "unpaid"}
        assert (
            by_result["unpaid"].link_url
            == "https://checkout.stripe.com/c/pay/cs_1"
        )
        unpaid = [
            p
            for p in await _payments(db_session)
            if p.state == "unpaid"
        ]
        assert len(unpaid) == 1
        assert unpaid[0].state_reason == "no_card"
        assert unpaid[0].stripe_checkout_session_id == "cs_1"
        assert unpaid[0].charge_requested_cents == 6000

    async def test_cap_at_estimate_caps_and_reports_shortfall(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """2 show against a goal of 4: true share $60, quoted $30.
        Capping charges the quote and surfaces the gap — never
        absorbs it silently."""
        event = await _seed_event(db_session)
        for n in (1, 3):
            await _seed_present_carded(
                db_session, event, f"+1555000000{n}"
            )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
            cap_at_estimate=True,
        )

        assert report.share_cents == 6000
        assert report.charge_cents == 3000
        assert report.shortfall_cents == 6000
        payments = await _payments(db_session)
        assert all(p.charged_cents == 3000 for p in payments)

    async def test_default_charges_actual_over_estimate(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """Silence never triggers absorbing: without the explicit
        cap flag the true (higher) share is charged."""
        event = await _seed_event(db_session)
        for n in (1, 3):
            await _seed_present_carded(
                db_session, event, f"+1555000000{n}"
            )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        assert report.charge_cents == 6000
        assert report.shortfall_cents == 0
        payments = await _payments(db_session)
        assert all(p.charged_cents == 6000 for p in payments)

    async def test_assume_all_attended_resolves_and_charges(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """going + unconfirmed under the assume default: attendance
        resolves in the same commit as the stamps, and they are
        charged like anyone marked by hand."""
        event = await _seed_event(db_session, state="closed")
        rsvp = await _seed_rsvp(
            db_session,
            event,
            phone="+15550000001",
            state="going",
            attendance="unconfirmed",
            stripe_customer_id="cus_1",
            stripe_payment_method_id="pm_1",
        )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        await db_session.refresh(rsvp)
        assert rsvp.state == "attended"
        assert rsvp.attendance == "present"
        assert report.share_cents == 12_000
        assert [o.result for o in report.outcomes] == ["paid"]

    async def test_mark_all_absent_skips_and_settles(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """going + unconfirmed under mark_all_absent: no_show,
        uncharged, out of the divisor — and the event still
        settles (charge nobody is a valid settlement)."""
        event = await _seed_event(
            db_session,
            state="closed",
            settle_default="mark_all_absent",
        )
        rsvp = await _seed_rsvp(
            db_session,
            event,
            phone="+15550000001",
            state="going",
            attendance="unconfirmed",
        )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        await db_session.refresh(rsvp)
        assert rsvp.state == "no_show"
        assert rsvp.attendance == "absent"
        assert report.share_cents == 0
        assert report.outcomes == ()
        assert await _payments(db_session) == []
        await db_session.refresh(event)
        assert event.state == "settled"
        mock_stripe.PaymentIntent.create_async.assert_not_awaited()

    async def test_settle_from_open_closes_first(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """Settlement beginning closes RSVPs (state_machines.md):
        open -> closed -> settled in one call."""
        event = await _seed_event(db_session, state="open")
        await _seed_present_carded(db_session, event, "+15550000001")
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        await db_session.refresh(event)
        assert event.state == "settled"

    async def test_zero_present_settles_with_no_charges(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        event = await _seed_event(db_session, state="closed")
        await _seed_rsvp(
            db_session,
            event,
            phone="+15550000001",
            state="no_show",
            attendance="absent",
        )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        assert report.share_cents == 0
        assert report.outcomes == ()
        assert await _payments(db_session) == []
        await db_session.refresh(event)
        assert event.state == "settled"

    async def test_stamps_commit_before_stripe_is_called(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """THE record-first check: at the instant Stripe is called
        there must be NO open transaction — the stamps and the
        Payment row are already durable. Moving the commit after
        the Stripe call must turn this red."""
        event = await _seed_event(db_session, state="closed")
        await _seed_present_carded(db_session, event, "+15550000001")
        planner = await db_session.get(Planner, event.planner_id)
        seen: dict[str, Any] = {}

        def _observe(**kwargs: Any) -> SimpleNamespace:
            seen["in_txn"] = db_session.in_transaction()
            return SimpleNamespace(id="pi_1", status="succeeded")

        mock_stripe.PaymentIntent.create_async = AsyncMock(
            side_effect=_observe
        )

        await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        assert seen["in_txn"] is False

    async def test_charge_amount_matches_stamp_and_kwargs(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """What Stripe is asked for == what was stamped == what the
        report says, per attendee, with per-row idempotency keys."""
        event = await _seed_event(
            db_session, total_cost_cents=7_000
        )
        for n in (1, 3):
            await _seed_present_carded(
                db_session, event, f"+1555000000{n}"
            )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        assert report.charge_cents == 3500
        calls = (
            mock_stripe.PaymentIntent.create_async.await_args_list
        )
        assert [c.kwargs["amount"] for c in calls] == [3500, 3500]
        payments = await _payments(db_session)
        keys = {c.kwargs["idempotency_key"] for c in calls}
        assert keys == {f"{p.id}:charge" for p in payments}
        assert all(
            p.charge_requested_cents == 3500 for p in payments
        )


def _decline(mock_stripe: MagicMock) -> Exception:
    """A real CardError shaped as the SDK ships it (payload on
    err.error) — same shape test_payments pins."""
    err = mock_stripe.CardError("declined", None, "card_declined")
    err.error = SimpleNamespace(
        decline_code="insufficient_funds",
        payment_intent=SimpleNamespace(id="pi_declined"),
    )
    return err


def _pi_by_customer(
    mock_stripe: MagicMock, failures: dict[str, Exception]
) -> AsyncMock:
    """Succeed per customer unless a failure is scripted — keyed by
    customer id, not call order, so row ordering can't flake."""

    def _create(**kwargs: Any) -> SimpleNamespace:
        customer = kwargs["customer"]
        if customer in failures:
            raise failures[customer]
        return SimpleNamespace(
            id=f"pi_{customer}", status="succeeded"
        )

    return AsyncMock(side_effect=_create)


class TestSettleFailures:
    async def test_decline_mid_settle_links_and_continues(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """One friend's card declines: they land unpaid with the
        reason AND a link minted in-settle; the other friend is
        still charged; the event still settles."""
        event = await _seed_event(db_session)
        await _seed_present_carded(db_session, event, "+15550000001")
        await _seed_present_carded(db_session, event, "+15550000003")
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _pi_by_customer(
            mock_stripe, {"cus_1": _decline(mock_stripe)}
        )
        mock_stripe.checkout.Session.create_async = AsyncMock(
            return_value=SimpleNamespace(
                id="cs_1",
                url="https://checkout.stripe.com/c/pay/cs_1",
            )
        )

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        by_result = {o.result: o for o in report.outcomes}
        assert set(by_result) == {"paid", "unpaid"}
        assert by_result["unpaid"].link_url is not None
        unpaid = [
            p
            for p in await _payments(db_session)
            if p.state == "unpaid"
        ]
        assert unpaid[0].state_reason == "insufficient_funds"
        assert unpaid[0].stripe_checkout_session_id == "cs_1"
        await db_session.refresh(event)
        assert event.state == "settled"

    async def test_api_error_mid_settle_dangles_and_continues(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """An API blip on one row: it stays dangling (state none,
        stamps intact), the report says so, the others charge, the
        event still settles."""
        event = await _seed_event(db_session)
        await _seed_present_carded(db_session, event, "+15550000001")
        await _seed_present_carded(db_session, event, "+15550000003")
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _pi_by_customer(
            mock_stripe,
            {"cus_1": mock_stripe.StripeError("api blip")},
        )

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        results = sorted(o.result for o in report.outcomes)
        assert results == ["dangling", "paid"]
        dangling = [
            p
            for p in await _payments(db_session)
            if p.state == "none"
        ]
        assert len(dangling) == 1
        assert dangling[0].charge_requested_at is not None
        assert dangling[0].charge_requested_cents == 6000
        await db_session.refresh(event)
        assert event.state == "settled"

    async def test_rerun_retries_dangling_with_stamped_cents(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """A crashed run left one paid row and one dangling row
        stamped at 5900 (≠ any recompute). Re-settle: the paid row
        gets NO Stripe call, the dangling row is charged EXACTLY
        the stamp, no duplicate rows."""
        event = await _seed_event(db_session, state="closed")
        paid_rsvp = await _seed_present_carded(
            db_session, event, "+15550000001"
        )
        dang_rsvp = await _seed_present_carded(
            db_session, event, "+15550000003"
        )
        planner = await db_session.get(Planner, event.planner_id)
        db_session.add_all(
            [
                Payment(
                    event_id=event.id,
                    attendee_id=paid_rsvp.attendee_id,
                    attempt=1,
                    state="paid",
                    charged_cents=6000,
                    stripe_payment_intent_id="pi_done",
                    charge_requested_at=STARTS_AT,
                    charge_requested_cents=6000,
                ),
                Payment(
                    event_id=event.id,
                    attendee_id=dang_rsvp.attendee_id,
                    attempt=1,
                    state="none",
                    charge_requested_at=STARTS_AT,
                    charge_requested_cents=5900,
                ),
            ]
        )
        await db_session.commit()
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        assert sorted(o.result for o in report.outcomes) == [
            "paid",
            "paid",
        ]
        calls = (
            mock_stripe.PaymentIntent.create_async.await_args_list
        )
        assert len(calls) == 1
        assert calls[0].kwargs["amount"] == 5900
        assert len(await _payments(db_session)) == 2
        await db_session.refresh(event)
        assert event.state == "settled"

    async def test_rerun_skips_unpaid_without_reminting(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """An unpaid row keeps its live link on re-run: no charge,
        no re-mint, session id untouched."""
        event = await _seed_event(db_session, state="closed")
        rsvp = await _seed_present_carded(
            db_session, event, "+15550000001"
        )
        planner = await db_session.get(Planner, event.planner_id)
        db_session.add(
            Payment(
                event_id=event.id,
                attendee_id=rsvp.attendee_id,
                attempt=1,
                state="unpaid",
                state_reason="insufficient_funds",
                stripe_checkout_session_id="cs_live",
                charge_requested_at=STARTS_AT,
                charge_requested_cents=6000,
            )
        )
        await db_session.commit()
        mock_stripe.PaymentIntent.create_async = AsyncMock()
        mock_stripe.checkout.Session.create_async = AsyncMock()
        mock_stripe.checkout.Session.expire_async = AsyncMock()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        assert [o.result for o in report.outcomes] == ["unpaid"]
        assert report.outcomes[0].link_url is None
        mock_stripe.PaymentIntent.create_async.assert_not_awaited()
        create = mock_stripe.checkout.Session.create_async
        create.assert_not_awaited()
        payments = await _payments(db_session)
        session_id = payments[0].stripe_checkout_session_id
        assert session_id == "cs_live"

    @pytest.mark.parametrize(
        "state", ["draft", "settled", "cancelled"]
    )
    async def test_settle_from_wrong_state_refuses(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    , state: str) -> None:
        event = await _seed_event(db_session, state=state)
        planner = await db_session.get(Planner, event.planner_id)

        with pytest.raises(ValueError):
            await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )
        assert event.state == state


class TestRetryDangling:
    async def _dangling(
        self, session: AsyncSession, *, carded: bool = True
    ) -> tuple[Payment, Attendee, Planner]:
        event = await _seed_event(session, state="closed")
        rsvp = (
            await _seed_present_carded(
                session, event, "+15550000001"
            )
            if carded
            else await _seed_rsvp(
                session,
                event,
                phone="+15550000001",
                state="attended",
                attendance="present",
            )
        )
        payment = Payment(
            event_id=event.id,
            attendee_id=rsvp.attendee_id,
            attempt=1,
            state="none",
            charge_requested_at=STARTS_AT,
            charge_requested_cents=3200,
        )
        session.add(payment)
        await session.commit()
        attendee = await session.get(Attendee, rsvp.attendee_id)
        planner = await session.get(Planner, event.planner_id)
        assert attendee is not None and planner is not None
        return payment, attendee, planner

    async def test_retry_charges_the_stamped_amount(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        from app.settlement import retry_dangling

        payment, attendee, planner = await self._dangling(
            db_session
        )
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        outcome = await retry_dangling(
            db_session,
            payment,
            attendee,
            planner,
            success_url="https://app.example/paid",
        )

        assert outcome.result == "paid"
        assert payment.state == "paid"
        calls = (
            mock_stripe.PaymentIntent.create_async.await_args_list
        )
        assert calls[0].kwargs["amount"] == 3200

    async def test_retry_refuses_non_dangling_rows(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        from app.settlement import retry_dangling

        payment, attendee, planner = await self._dangling(
            db_session
        )
        payment.state = "unpaid"
        await db_session.commit()
        mock_stripe.PaymentIntent.create_async = AsyncMock()

        with pytest.raises(ValueError):
            await retry_dangling(
                db_session,
                payment,
                attendee,
                planner,
                success_url="https://app.example/paid",
            )
        mock_stripe.PaymentIntent.create_async.assert_not_awaited()

    async def test_retry_cardless_dangling_mints_link(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        from app.settlement import retry_dangling

        payment, attendee, planner = await self._dangling(
            db_session, carded=False
        )
        mock_stripe.checkout.Session.create_async = AsyncMock(
            return_value=SimpleNamespace(
                id="cs_9",
                url="https://checkout.stripe.com/c/pay/cs_9",
            )
        )

        outcome = await retry_dangling(
            db_session,
            payment,
            attendee,
            planner,
            success_url="https://app.example/paid",
        )

        assert outcome.result == "unpaid"
        assert (
            outcome.link_url
            == "https://checkout.stripe.com/c/pay/cs_9"
        )
        assert payment.state == "unpaid"
        assert payment.state_reason == "no_card"
        assert payment.stripe_checkout_session_id == "cs_9"


_grossup = pytest.mark.xfail(
    strict=True,
    reason="gross_up step: settlement wiring is owner-authored "
    "against these (NOTES.md checkpoint, 2026-07-18)",
)


class TestGrossUp:
    """The gross-up wiring (shaping calls confirmed 2026-07-18):
    every billed surface — the Stripe amount, the record-first
    stamp, charged_cents — carries gross_up(share); the report
    shows share/billed/netted; the cap compares grossed-to-grossed.
    RED until settlement.py is wired; the existing un-grossed
    assertions elsewhere in this file get updated in that step."""

    @_grossup
    async def test_billed_amount_is_grossed_up_share(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """$120 ÷ 4 (planner plays) = $30.00 net share, billed
        $31.21 — stamp, Stripe kwarg, and charged_cents all agree,
        and the report separates split / billed / netted."""
        event = await _seed_event(db_session)
        await _planner_plays(db_session, event)
        for n in (1, 3, 4):
            await _seed_present_carded(
                db_session, event, f"+1555000000{n}"
            )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
        )

        assert report.share_cents == 3000
        assert report.billed_cents == 3121
        assert report.netted_cents == 3000
        assert report.shortfall_cents == 0
        calls = (
            mock_stripe.PaymentIntent.create_async.await_args_list
        )
        assert [c.kwargs["amount"] for c in calls] == [3121] * 3
        payments = await _payments(db_session)
        assert all(
            p.charge_requested_cents == 3121
            and p.charged_cents == 3121
            for p in payments
        )

    @_grossup
    async def test_cap_compares_grossed_to_grossed(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """Actual == quoted, so the cap must be a no-op. The
        estimate is STORED grossed ($31.21 quoting a $30.00 net);
        the old min(net, gross) would bill only $30.00 and
        silently under-net the planner by the whole fee."""
        event = await _seed_event(
            db_session, estimated_share_cents=3_121
        )
        await _planner_plays(db_session, event)
        for n in (1, 3, 4):
            await _seed_present_carded(
                db_session, event, f"+1555000000{n}"
            )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
            cap_at_estimate=True,
        )

        assert report.billed_cents == 3121
        assert report.netted_cents == 3000
        assert report.shortfall_cents == 0

    @_grossup
    async def test_cap_absorbs_in_net_terms(
        self, db_session: AsyncSession, mock_stripe: MagicMock
    ) -> None:
        """Three of the goal-four show: share $40.00 > quoted.
        Cap mode bills the quoted gross ($31.21), nets the quoted
        net ($30.00), and the absorbed gap is reported in NET
        terms: ($40 − $30) × 3 charged = $30.00 — never silent."""
        event = await _seed_event(
            db_session, estimated_share_cents=3_121
        )
        for n in (1, 3, 4):
            await _seed_present_carded(
                db_session, event, f"+1555000000{n}"
            )
        planner = await db_session.get(Planner, event.planner_id)
        mock_stripe.PaymentIntent.create_async = _succeeding_pi()

        report = await settle_event(
            db_session,
            event,
            planner,
            success_url="https://app.example/paid",
            cap_at_estimate=True,
        )

        assert report.share_cents == 4000
        assert report.billed_cents == 3121
        assert report.netted_cents == 3000
        assert report.shortfall_cents == 3000
        calls = (
            mock_stripe.PaymentIntent.create_async.await_args_list
        )
        assert [c.kwargs["amount"] for c in calls] == [3121] * 3


async def test_sub_minimum_share_refused_before_any_stamp(
    db_session: AsyncSession, mock_stripe: MagicMock
) -> None:
    """Phone walk 2026-07-19: a $1÷3 event put every charge under
    Stripe's 50¢ floor — they landed dangling with no explanation.
    The guard refuses LOUDLY before any record-first stamp, so
    nothing is half-settled."""
    event = await _seed_event(
        db_session,
        total_cost_cents=100,
        estimated_share_cents=33,
        state="closed",
    )
    for phone in (
        "+15550000003",
        "+15550000004",
        "+15550000005",
    ):
        await _seed_present_carded(db_session, event, phone)
    planner = await db_session.get(Planner, event.planner_id)
    assert planner is not None
    with pytest.raises(ValueError, match="50"):
        await settle_event(
            db_session,
            event,
            planner,
            success_url="https://x/paid",
        )
    assert await _payments(db_session) == []
    await db_session.refresh(event)
    assert event.state == "closed"
    mock_stripe.PaymentIntent.create_async.assert_not_called()
