"""Contract tests for app/payments.py (charge-at-close).

Test-first per CLAUDE.md: these pin each body's mechanism against
the mocked stripe module — exact kwargs included, because for money
code the Stripe params ARE the contract. No test touches the live
API: conftest's mock_stripe fixture injects the mock into
app.payments and the autouse fixture blanks the credentials.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import Attendee, Payment, Planner
from app.payments import (
    CardSaveFailed,
    charge_share,
    create_setup_intent,
    record_saved_card,
)

STAMPED_AT = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)


def _attendee(**overrides: Any) -> Attendee:
    fields: dict[str, Any] = {
        "id": 7,
        "name": "Ana Attendee",
        "phone": "+15550000001",
    }
    fields.update(overrides)
    return Attendee(**fields)


def _carded_attendee(**overrides: Any) -> Attendee:
    return _attendee(
        stripe_customer_id="cus_1",
        stripe_payment_method_id="pm_77",
        **overrides,
    )


def _planner(**overrides: Any) -> Planner:
    fields: dict[str, Any] = {
        "id": 3,
        "name": "Pat Planner",
        "phone": "+15550000002",
        "stripe_account_id": "acct_9",
    }
    fields.update(overrides)
    return Planner(**fields)


def _payment(**overrides: Any) -> Payment:
    """A Payment the caller has already stamped record-first
    (charge_requested_at + charge_requested_cents), state `none`."""
    fields: dict[str, Any] = {
        "id": 41,
        "event_id": 11,
        "attendee_id": 7,
        "attempt": 1,
        "state": "none",
        "charge_requested_at": STAMPED_AT,
        "charge_requested_cents": 3200,
    }
    fields.update(overrides)
    return Payment(**fields)


def _card_error(
    mock_stripe: MagicMock,
    code: str = "card_declined",
    decline_code: str | None = "insufficient_funds",
) -> Exception:
    """A real CardError (the class conftest attached) shaped the
    way the SDK ships it: the parsed payload rides on err.error,
    carrying the bank's decline_code and the declined PI."""
    err = mock_stripe.CardError("declined", None, code)
    err.error = SimpleNamespace(
        decline_code=decline_code,
        payment_intent=SimpleNamespace(id="pi_declined"),
    )
    return err


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


class TestChargeShare:
    async def test_happy_path_charges_and_marks_paid(
        self, mock_stripe: MagicMock
    ) -> None:
        """none -> paid; the kwargs ARE the money contract: exact
        amount, off-session immediate capture, planner as merchant
        of record and destination, fixed idempotency key."""
        payment = _payment()
        mock_stripe.PaymentIntent.create_async = AsyncMock(
            return_value=SimpleNamespace(
                id="pi_ok", status="succeeded"
            )
        )

        result = await charge_share(
            payment, _carded_attendee(), _planner(), 3200
        )

        assert result is payment
        assert payment.state == "paid"
        assert payment.charged_cents == 3200
        assert payment.stripe_payment_intent_id == "pi_ok"
        create = mock_stripe.PaymentIntent.create_async
        create.assert_awaited_once_with(
            amount=3200,
            currency="usd",
            customer="cus_1",
            payment_method="pm_77",
            confirm=True,
            off_session=True,
            on_behalf_of="acct_9",
            transfer_data={"destination": "acct_9"},
            metadata={
                "payment_id": "41",
                "event_id": "11",
                "attendee_id": "7",
            },
            idempotency_key="41:charge",
        )

    async def test_decline_lands_unpaid_and_records_the_pi(
        self, mock_stripe: MagicMock
    ) -> None:
        """A decline is an OUTCOME, not an exception: none ->
        unpaid, the bank's SPECIFIC reason recorded, and the
        declined PI kept on the row (decisions.md 2026-07-16) —
        the DB must know at least as much as Stripe."""
        payment = _payment()
        mock_stripe.PaymentIntent.create_async = AsyncMock(
            side_effect=_card_error(mock_stripe)
        )

        result = await charge_share(
            payment, _carded_attendee(), _planner(), 3200
        )

        assert result is payment
        assert payment.state == "unpaid"
        assert payment.state_reason == "insufficient_funds"
        assert payment.stripe_payment_intent_id == "pi_declined"
        assert payment.charged_cents is None

    async def test_decline_reason_falls_back_to_the_broad_code(
        self, mock_stripe: MagicMock
    ) -> None:
        """No bank decline_code (e.g. deferred-3DS
        authentication_required) -> record the broad code; the
        attendee still lands on the on-session link path."""
        payment = _payment()
        mock_stripe.PaymentIntent.create_async = AsyncMock(
            side_effect=_card_error(
                mock_stripe,
                code="authentication_required",
                decline_code=None,
            )
        )

        await charge_share(
            payment, _carded_attendee(), _planner(), 3200
        )

        assert payment.state == "unpaid"
        assert payment.state_reason == "authentication_required"

    async def test_non_succeeded_intent_never_marks_paid(
        self, mock_stripe: MagicMock
    ) -> None:
        """Never assume collected (CLAUDE.md): a returned intent
        that is not 'succeeded' must not write `paid` — raise and
        leave the row dangling for a same-key retry."""
        payment = _payment()
        mock_stripe.PaymentIntent.create_async = AsyncMock(
            return_value=SimpleNamespace(
                id="pi_odd", status="processing"
            )
        )

        with pytest.raises(RuntimeError):
            await charge_share(
                payment, _carded_attendee(), _planner(), 3200
            )
        assert payment.state == "none"
        assert payment.charged_cents is None
        assert payment.stripe_payment_intent_id is None

    async def test_missing_stamp_refuses_before_stripe(
        self, mock_stripe: MagicMock
    ) -> None:
        """Record-first: no charge_requested_at stamp means the
        intent was never written — refuse to move money."""
        payment = _payment(charge_requested_at=None)
        mock_stripe.PaymentIntent.create_async = AsyncMock()

        with pytest.raises(ValueError):
            await charge_share(
                payment, _carded_attendee(), _planner(), 3200
            )
        mock_stripe.PaymentIntent.create_async.assert_not_awaited()
        assert payment.state == "none"

    async def test_drifted_amount_refuses_before_stripe(
        self, mock_stripe: MagicMock
    ) -> None:
        """Intent includes the amount (decisions.md 2026-07-16): a
        retry must re-send exactly what was stamped, or Stripe's
        idempotency replay would strand the row. Drift fails HERE,
        loudly, not as an opaque IdempotencyError."""
        payment = _payment(charge_requested_cents=3200)
        mock_stripe.PaymentIntent.create_async = AsyncMock()

        with pytest.raises(ValueError):
            await charge_share(
                payment, _carded_attendee(), _planner(), 3000
            )
        mock_stripe.PaymentIntent.create_async.assert_not_awaited()
        assert payment.state == "none"

    @pytest.mark.parametrize(
        "state", ["unpaid", "paid", "refunded", "abandoned"]
    )
    async def test_fires_from_none_only(
        self, mock_stripe: MagicMock, state: str
    ) -> None:
        """decisions.md 2026-07-16: the saved card is charged once
        per row; the tap-to-pay link is the only recovery from
        unpaid. Anything but `none` refuses before Stripe."""
        payment = _payment(state=state)
        mock_stripe.PaymentIntent.create_async = AsyncMock()

        with pytest.raises(ValueError):
            await charge_share(
                payment, _carded_attendee(), _planner(), 3200
            )
        mock_stripe.PaymentIntent.create_async.assert_not_awaited()
        assert payment.state == state

    async def test_cardless_attendee_refuses_before_stripe(
        self, mock_stripe: MagicMock
    ) -> None:
        """No saved card -> this attendee belongs on the tap-to-pay
        path; calling charge_share for them is a caller bug."""
        payment = _payment()
        attendee = _attendee(stripe_customer_id="cus_1")
        mock_stripe.PaymentIntent.create_async = AsyncMock()

        with pytest.raises(ValueError):
            await charge_share(payment, attendee, _planner(), 3200)
        mock_stripe.PaymentIntent.create_async.assert_not_awaited()
        assert payment.state == "none"

    @pytest.mark.parametrize("cents", [0, -100, 31.99, True])
    async def test_non_positive_or_non_int_cents_refused(
        self, mock_stripe: MagicMock, cents: Any
    ) -> None:
        """Integer cents, never float (CLAUDE.md); bool is an int
        subclass and must not slip through."""
        payment = _payment(charge_requested_cents=None)
        mock_stripe.PaymentIntent.create_async = AsyncMock()

        with pytest.raises(ValueError):
            await charge_share(
                payment, _carded_attendee(), _planner(), cents
            )
        mock_stripe.PaymentIntent.create_async.assert_not_awaited()

    async def test_non_card_stripe_error_leaves_row_dangling(
        self, mock_stripe: MagicMock
    ) -> None:
        """An API blip is NOT an outcome: propagate, leave the row
        dangling (stamp set, state none) so the retry replays the
        SAME idempotency key and the books converge."""
        payment = _payment()
        mock_stripe.PaymentIntent.create_async = AsyncMock(
            side_effect=mock_stripe.StripeError("api blip")
        )

        with pytest.raises(mock_stripe.StripeError):
            await charge_share(
                payment, _carded_attendee(), _planner(), 3200
            )
        assert payment.state == "none"
        assert payment.charged_cents is None
        assert payment.stripe_payment_intent_id is None
