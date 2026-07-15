"""Capability-URL token minting (decisions.md 2026-07-13/16).

The web layer's route lookups rely on exactly these properties:
every row mints its own token at insert (no service code asked),
one token per purpose, URL-safe, and unique by DB constraint.
"""
import string
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.bootstrap import create_tables
from app.models import Attendee, Event, Planner, Rsvp

# token_urlsafe output: base64url alphabet, no padding
URL_SAFE = set(string.ascii_letters + string.digits + "-_")


async def _planner(session: AsyncSession, phone: str) -> Planner:
    planner = Planner(
        name="Noah", phone=phone, stripe_account_id="acct_test"
    )
    session.add(planner)
    await session.commit()
    return planner


async def _event(session: AsyncSession, planner_id: int) -> Event:
    event = Event(
        planner_id=planner_id,
        title="Tuesday pickleball",
        starts_at=datetime(2026, 7, 21, 18, tzinfo=timezone.utc),
        total_cost_cents=12000,
        goal_attendance=4,
        estimated_share_cents=3000,
    )
    session.add(event)
    await session.commit()
    return event


async def test_event_insert_mints_both_tokens(
    db_session: AsyncSession,
) -> None:
    planner = await _planner(db_session, "+15550000001")
    event = await _event(db_session, planner.id)
    for token in (event.event_token, event.admin_token):
        assert len(token) == 22
        assert set(token) <= URL_SAFE
    # One token per purpose, never shared across purposes
    assert event.event_token != event.admin_token


async def test_rsvp_insert_mints_token(
    db_session: AsyncSession,
) -> None:
    planner = await _planner(db_session, "+15550000001")
    event = await _event(db_session, planner.id)
    attendee = Attendee(name="Sam", phone="+15550000002")
    db_session.add(attendee)
    await db_session.commit()
    rsvp = Rsvp(event_id=event.id, attendee_id=attendee.id)
    db_session.add(rsvp)
    await db_session.commit()
    assert len(rsvp.rsvp_token) == 22
    assert set(rsvp.rsvp_token) <= URL_SAFE


async def test_tokens_distinct_across_rows(
    db_session: AsyncSession,
) -> None:
    planner = await _planner(db_session, "+15550000001")
    first = await _event(db_session, planner.id)
    second = await _event(db_session, planner.id)
    tokens = {
        first.event_token,
        first.admin_token,
        second.event_token,
        second.admin_token,
    }
    assert len(tokens) == 4


async def test_duplicate_token_insert_fails(
    db_session: AsyncSession,
) -> None:
    """The unique index is enforced, not decorative: if a duplicate
    ever appeared, two links would share one capability — the DB
    must refuse loudly, never store it."""
    planner = await _planner(db_session, "+15550000001")
    first = await _event(db_session, planner.id)
    clone = Event(
        planner_id=planner.id,
        title="Clone",
        starts_at=datetime(2026, 7, 22, 18, tzinfo=timezone.utc),
        total_cost_cents=12000,
        goal_attendance=4,
        estimated_share_cents=3000,
        event_token=first.event_token,
    )
    db_session.add(clone)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_bootstrap_create_tables_idempotent() -> None:
    """python -m app.bootstrap must be safe to re-run: create_all
    adds missing tables and leaves existing ones untouched."""
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool
    )
    await create_tables(engine)
    await create_tables(engine)  # re-run: no error, no change
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        planner = Planner(
            name="Noah",
            phone="+15550000001",
            stripe_account_id="acct_test",
        )
        session.add(planner)
        await session.commit()
        assert planner.id is not None
    await engine.dispose()
