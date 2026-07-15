"""Contract tests for app/payments.py (charge-at-close).

Test-first per CLAUDE.md: these pin each body's mechanism against
the mocked stripe module — exact kwargs included, because for money
code the Stripe params ARE the contract. No test touches the live
API: conftest's mock_stripe fixture injects the mock into
app.payments and the autouse fixture blanks the credentials.
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import Attendee
from app.payments import (
    CardSaveFailed,
    create_setup_intent,
    record_saved_card,
)


def _attendee(**overrides: Any) -> Attendee:
    fields: dict[str, Any] = {
        "id": 7,
        "name": "Ana Attendee",
        "phone": "+15550000001",
    }
    fields.update(overrides)
    return Attendee(**fields)


def _setup_intent(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "id": "seti_1",
        "customer": "cus_1",
        "status": "succeeded",
        "payment_method": "pm_77",
        "client_secret": "seti_1_secret_x",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class TestCreateSetupIntent:
    async def test_first_save_creates_platform_customer(
        self, mock_stripe: MagicMock
    ) -> None:
        """No customer yet: create one on the PLATFORM account
        (destination charges require it — skeleton_02), persist its
        id, and open an off-session SetupIntent on it."""
        attendee = _attendee()
        mock_stripe.Customer.create_async = AsyncMock(
            return_value=SimpleNamespace(id="cus_1")
        )
        mock_stripe.SetupIntent.create_async = AsyncMock(
            return_value=_setup_intent()
        )

        secret = await create_setup_intent(attendee)

        assert secret == "seti_1_secret_x"
        assert attendee.stripe_customer_id == "cus_1"
        mock_stripe.Customer.create_async.assert_awaited_once_with(
            name="Ana Attendee",
            phone="+15550000001",
            metadata={"attendee_id": "7"},
        )
        mock_stripe.SetupIntent.create_async.assert_awaited_once_with(
            customer="cus_1",
            usage="off_session",
            payment_method_types=["card"],
            metadata={"attendee_id": "7"},
        )

    async def test_existing_customer_is_reused(
        self, mock_stripe: MagicMock
    ) -> None:
        """A returning attendee must not get a duplicate Customer."""
        attendee = _attendee(stripe_customer_id="cus_9")
        mock_stripe.Customer.create_async = AsyncMock()
        mock_stripe.SetupIntent.create_async = AsyncMock(
            return_value=_setup_intent(customer="cus_9")
        )

        await create_setup_intent(attendee)

        mock_stripe.Customer.create_async.assert_not_awaited()
        kwargs = mock_stripe.SetupIntent.create_async.await_args.kwargs
        assert kwargs["customer"] == "cus_9"


class TestRecordSavedCard:
    async def test_success_persists_payment_method(
        self, mock_stripe: MagicMock
    ) -> None:
        """Finalize retrieves by id (never trusts the client's claim
        about status) and persists the payment method."""
        attendee = _attendee(stripe_customer_id="cus_1")
        mock_stripe.SetupIntent.retrieve_async = AsyncMock(
            return_value=_setup_intent()
        )

        result = await record_saved_card(attendee, "seti_1")

        assert result is attendee
        assert attendee.stripe_payment_method_id == "pm_77"
        retrieve = mock_stripe.SetupIntent.retrieve_async
        retrieve.assert_awaited_once_with("seti_1")

    async def test_foreign_setup_intent_is_rejected(
        self, mock_stripe: MagicMock
    ) -> None:
        """A tampered SetupIntent id must not attach someone else's
        card to this attendee."""
        attendee = _attendee(stripe_customer_id="cus_1")
        mock_stripe.SetupIntent.retrieve_async = AsyncMock(
            return_value=_setup_intent(customer="cus_other")
        )

        with pytest.raises(ValueError):
            await record_saved_card(attendee, "seti_1")
        assert attendee.stripe_payment_method_id is None

    async def test_attendee_without_customer_is_rejected(
        self, mock_stripe: MagicMock
    ) -> None:
        """No platform Customer means no SetupIntent can be ours;
        refuse before any Stripe call."""
        attendee = _attendee()
        mock_stripe.SetupIntent.retrieve_async = AsyncMock()

        with pytest.raises(ValueError):
            await record_saved_card(attendee, "seti_1")
        mock_stripe.SetupIntent.retrieve_async.assert_not_awaited()

    @pytest.mark.parametrize(
        "status", ["requires_action", "processing", "canceled"]
    )
    async def test_unsucceeded_save_raises_card_save_failed(
        self, mock_stripe: MagicMock, status: str
    ) -> None:
        """Anything short of 'succeeded' is a failed save: the
        attendee retries or goes cardless — never a silent no-op."""
        attendee = _attendee(stripe_customer_id="cus_1")
        mock_stripe.SetupIntent.retrieve_async = AsyncMock(
            return_value=_setup_intent(
                status=status, payment_method=None
            )
        )

        with pytest.raises(CardSaveFailed):
            await record_saved_card(attendee, "seti_1")
        assert attendee.stripe_payment_method_id is None
