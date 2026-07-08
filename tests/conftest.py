"""Shared test fixtures.

Rule (CLAUDE.md): tests never call the live Stripe API. Two layers:
the secret key is scrubbed from the environment so accidental
`os.environ["STRIPE_SECRET_KEY"]` reads fail loudly, and payment
tests take the `mock_stripe` fixture instead of the real SDK.
"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def no_live_stripe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any path that reaches for real Stripe credentials fail
    loudly instead of silently hitting the API."""
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("TEST_PLANNER_ACCOUNT_ID", raising=False)


@pytest.fixture
def mock_stripe() -> MagicMock:
    """Stand-in for the stripe module: payment code under test gets
    this injected, and assertions run against the recorded calls."""
    stripe = MagicMock(name="stripe")
    stripe.api_key = "sk_test_mocked"
    return stripe
