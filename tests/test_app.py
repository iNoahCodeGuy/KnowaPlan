"""App scaffold smoke tests — importable and serving with no
Postgres and no Stripe credentials (conftest scrubs them)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Payment
from app.payments import (
    charge_share,
    create_payment_link,
    poll_link_status,
    refund_charge,
)


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
    cases = (
        (charge_share, (p, 3200)),
        (create_payment_link, (p, 3200)),
        (poll_link_status, (p,)),
        (refund_charge, (p, 3200)),
    )
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
    assert settings.test_planner_account_id == ""
