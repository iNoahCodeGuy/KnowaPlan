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
