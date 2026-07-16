"""Shared test fixtures.

Rule (CLAUDE.md): tests never call the live Stripe API. Two layers:
credentials are blanked for the whole test process, and payment
tests take the `mock_stripe` fixture instead of the real SDK.
"""
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
import stripe as real_stripe
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.main import app
from app.models import Base


@pytest.fixture(autouse=True)
def no_live_stripe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank the credentials — do not delete them. pydantic-settings
    reads the .env file itself, and only a PRESENT env var overrides
    it; deleting would let the real key from .env through."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    monkeypatch.setenv("PLANNER_ACCOUNT_ID", "")
    monkeypatch.setenv("CREATE_PASSWORD", "")
    # Not a secret, but tests must not depend on the developer's
    # .env: the missing-key page test only passed before because
    # the local .env happened to misname this variable.
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "")


@pytest.fixture
def mock_stripe(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stand-in for the stripe module, injected into app.payments:
    the code under test talks to this, and assertions run against
    the recorded calls. except-clauses need REAL exception classes
    (a MagicMock attribute cannot be caught), so those come from the
    SDK — importing it makes no network call."""
    stripe = MagicMock(name="stripe")
    stripe.api_key = "sk_test_mocked"
    stripe.CardError = real_stripe.CardError
    stripe.StripeError = real_stripe.StripeError
    monkeypatch.setattr("app.payments.stripe", stripe)
    return stripe


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Real async session on in-memory SQLite: record-first commit
    ordering is tested against real commits, hermetically. SQLite
    stores tz-naive datetimes — fine for ordering tests; Postgres
    fidelity comes with live dogfood (decisions.md 2026-07-16)."""
    # StaticPool pins ONE connection: an in-memory SQLite database
    # lives per connection, and a second pooled connection would be
    # a second, empty database.
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(
    db_session: AsyncSession,
) -> AsyncIterator[AsyncClient]:
    """ASGI test client with the app's DB dependency pointed at the
    in-memory session: web tests exercise real routes against a
    real (hermetic) DB, and mock_stripe keeps Stripe out."""

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()
