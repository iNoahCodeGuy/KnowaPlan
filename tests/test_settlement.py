"""Settlement service tests — real DB session (in-memory SQLite,
conftest db_session), mocked Stripe where money is involved. The
transactional claims (one commit per action; record-first ordering
in later steps) are pinned against real commits, and persistence is
verified by refreshing from the DB, never by trusting the object.
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee, Event, Planner, Rsvp
from app.settlement import close_rsvps, mark_attendance

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
