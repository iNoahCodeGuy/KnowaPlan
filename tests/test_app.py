"""App scaffold smoke tests — importable and serving with no
Postgres and no Stripe credentials (conftest scrubs them)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Payment
from app.payments import refund_charge


def test_health() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_payment_stubs_are_unwritten() -> None:
    """Money-moving bodies are authored with review (CLAUDE.md);
    until then they must refuse loudly, never no-op. Implemented
    functions graduate to tests/test_payments.py and leave this
    list; refund_charge stays until walk-ins ship."""
    p = Payment()
    # Build each coroutine inside the loop: pre-building the tuple
    # would leak never-awaited coroutines if an early case fails
    cases = ((refund_charge, (p, 3200)),)
    for func, args in cases:
        with pytest.raises(NotImplementedError):
            await func(*args)


def test_settings_never_see_live_credentials() -> None:
    """pydantic-settings reads .env directly; the conftest scrub
    must beat the real key. If this fails, tests can reach the
    live Stripe API — fix before anything else."""
    from app.config import get_settings

    settings = get_settings()
    assert settings.stripe_secret_key == ""
    assert settings.planner_account_id == ""
    assert settings.create_password == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Railway/Render hand out a driverless scheme
        (
            "postgresql://u:p@host.internal:5432/railway",
            "postgresql+asyncpg://u:p@host.internal:5432/railway",
        ),
        # Heroku's legacy postgres:// (no "ql")
        (
            "postgres://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        # already named a driver — untouched
        (
            "postgresql+asyncpg://u:p@host/db",
            "postgresql+asyncpg://u:p@host/db",
        ),
        # non-Postgres (tests/local) — untouched
        ("sqlite+aiosqlite://", "sqlite+aiosqlite://"),
    ],
)
def test_normalize_db_url(raw: str, expected: str) -> None:
    from app.config import _normalize_db_url

    assert _normalize_db_url(raw) == expected


def test_settings_normalizes_env_db_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A managed host's DATABASE_URL must be usable verbatim — the
    validator adds the async driver so create_async_engine works
    without the deployer editing the scheme by hand."""
    from app.config import Settings

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://u:p@host.internal:5432/railway",
    )
    assert Settings().database_url.startswith(
        "postgresql+asyncpg://"
    )


async def test_engine_pings_pooled_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Managed Postgres reaps idle connections; pool_pre_ping is
    what keeps the first request after a quiet stretch from
    landing on a dead one. Pins the flag on the engine our app
    actually builds. DATABASE_URL is pinned here because the
    outcome must not depend on the developer's .env (a sync-driver
    URL there would fail engine construction, not the assertion);
    save/restore the lazy singleton so the probe engine never
    leaks into other tests."""
    from app import db

    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")
    saved = (db._engine, db._sessionmaker)
    db._engine = db._sessionmaker = None
    try:
        engine = db.get_engine()
        assert engine.sync_engine.pool._pre_ping is True
        await engine.dispose()
    finally:
        db._engine, db._sessionmaker = saved


def test_unhandled_error_renders_branded_page() -> None:
    """An uncaught exception must show the friendly error page,
    not a bare 'Internal Server Error' — and must never leak the
    exception text to the person tapping the link."""
    route_path = "/_test_boom"

    @app.get(route_path)
    async def _boom() -> None:
        raise RuntimeError("secret-internals")

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(route_path)
        assert resp.status_code == 500
        assert "text the planner" in resp.text
        # A crash must not wear the refusal heading: "Can't do
        # that" implies nothing happened, and a mid-settle crash
        # can land after a charge.
        assert "Something went wrong" in resp.text
        assert "Can't do that" not in resp.text
        assert "secret-internals" not in resp.text
    finally:
        app.router.routes[:] = [
            r
            for r in app.router.routes
            if getattr(r, "path", None) != route_path
        ]


def test_stripe_id_columns_hold_real_stripe_ids() -> None:
    """Stripe publishes no id-length contract, and a real
    cs_test_ id overflowed VARCHAR(64) — the failed write orphaned
    a live Checkout link (decisions.md 2026-07-16). SQLite ignores
    VARCHAR lengths, so this pins the DECLARED capacity instead:
    every Stripe id column must hold at least 255 chars."""
    from app.models import Attendee, Payment, Planner

    columns = [
        Planner.__table__.c.stripe_account_id,
        Attendee.__table__.c.stripe_customer_id,
        Attendee.__table__.c.stripe_payment_method_id,
        Payment.__table__.c.stripe_payment_intent_id,
        Payment.__table__.c.stripe_checkout_session_id,
    ]
    for column in columns:
        assert column.type.length >= 255, column.name
