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

        report = await settle_event(db_session, event, planner)

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

        report = await settle_event(db_session, event, planner)

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

        report = await settle_event(db_session, event, planner)

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
            db_session, event, planner, cap_at_estimate=True
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

        report = await settle_event(db_session, event, planner)

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

        report = await settle_event(db_session, event, planner)

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

        report = await settle_event(db_session, event, planner)

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

        await settle_event(db_session, event, planner)

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

        report = await settle_event(db_session, event, planner)

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

        await settle_event(db_session, event, planner)

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

        report = await settle_event(db_session, event, planner)

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
