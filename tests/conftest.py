"""Shared test fixtures.

Rule (CLAUDE.md): tests never call the live Stripe API. Two layers:
credentials are blanked for the whole test process, and payment
tests take the `mock_stripe` fixture instead of the real SDK.
"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def no_live_stripe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank the credentials — do not delete them. pydantic-settings
    reads the .env file itself, and only a PRESENT env var overrides
    it; deleting would let the real key from .env through."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    monkeypatch.setenv("TEST_PLANNER_ACCOUNT_ID", "")


@pytest.fixture
def mock_stripe() -> MagicMock:
    """Stand-in for the stripe module: payment code under test gets
    this injected, and assertions run against the recorded calls."""
    stripe = MagicMock(name="stripe")
    stripe.api_key = "sk_test_mocked"
    return stripe
