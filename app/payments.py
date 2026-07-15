"""Payment operations — MECHANISM DOCUMENTED, BODIES UNWRITTEN.

Per CLAUDE.md, money-moving code is authored or reviewed by the
project owner; these stubs pin the contracts and the Stripe
mechanism so the bodies can be filled in deliberately. skeleton_02
is the proven reference for the PaymentIntent create call.

Charge-at-close (decisions.md 2026-07-15) — no holds:
- Save card: a SetupIntent at RSVP saves the attendee's card to a
  PLATFORM Customer for later off-session use (usage="off_session",
  so any 3DS runs now, while the attendee is present). No money
  moves. create_setup_intent → client_secret; record_saved_card
  finalizes once the browser confirms (no webhook — decisions.md
  2026-07-13 — so the browser hands the SetupIntent id back).
- Charge at close: charge_share creates a PaymentIntent for the
  actual share (confirm=True, off_session=True, on_behalf_of and
  transfer_data.destination = planner). Immediate capture — no
  manual-capture hold. Success -> paid; a CardError -> unpaid.
- Cardless / decline: create_payment_link opens a one-time Checkout
  Session (the tap-to-pay link the planner texts); poll_link_status
  reads its status on roster load to move unpaid -> paid (option b,
  no webhook).
- Refund: refund_charge reverses a COLLECTED charge only
  (paid -> refunded). Deferred in v0 with walk-ins; the state and
  the money_guard marker exist for when it ships.

Invariants every body must keep:
- Amounts are integer cents.
- Money-moving calls pass an idempotency_key derived from
  (payment.id, operation): "{payment.id}:charge" for a saved-card
  charge, "{payment.id}:refund" for a reversal. A re-added attendee
  is a NEW Payment row (fresh key by construction); a network-blip
  retry of the SAME operation reuses its key and cannot double-move.
  Link creation is the exception — a Checkout Session expires, so a
  fixed key would replay a dead session (see create_payment_link).
- Record-first: the CALLER stamps charge_requested_at AND
  charge_requested_cents (intent = when and how much — decisions.md
  2026-07-16) in the same DB transaction as the attendance change,
  BEFORE calling charge_share; the terminal state (paid/unpaid) is
  written after. A dangling charge (stamp set, state still `none`)
  is queryable and retried with the SAME idempotency key — and
  identical params by construction, so Stripe replays the original
  outcome. The DB must always know at least as much as Stripe.
- Never call the live Stripe API in tests — inject a mock (conftest
  mock_stripe).
"""
import stripe

from app.config import get_settings
from app.models import Attendee, Payment, Planner
from app.state_machines import PAYMENT, can_transition


class CardSaveFailed(Exception):
    """The SetupIntent did not succeed — the attendee retries with
    another card or proceeds cardless (scenarios.md: card fails to
    save at RSVP). Carries the SetupIntent status."""


def _configure() -> None:
    # Lazy on purpose: tests blank the key and inject a mock module
    # (conftest); the real key is read only when a call is made.
    stripe.api_key = get_settings().stripe_secret_key


def _validate_cents(actual_cents: int) -> None:
    # bool is an int subclass; True must not read as 1 cent.
    if isinstance(actual_cents, bool) or not isinstance(
        actual_cents, int
    ):
        raise ValueError("amounts are integer cents (CLAUDE.md)")
    if actual_cents <= 0:
        raise ValueError("charge amount must be positive cents")


def _move(payment: Payment, dst: str) -> None:
    # models.py contract: every state write checks the table, so an
    # illegal move is a loud error, never a silent typo.
    if not can_transition(PAYMENT, payment.state, dst):
        raise ValueError(
            f"illegal Payment move {payment.state!r} -> {dst!r}"
        )
    payment.state = dst


async def create_setup_intent(attendee: Attendee) -> str:
    """Save a card at RSVP: create a SetupIntent on the platform
    Customer (creating the Customer first if needed) and return its
    client_secret for the browser's Payment Element. Moves no money;
    usage="off_session" so any 3DS runs on-session, now."""
    _configure()
    if attendee.stripe_customer_id is None:
        # Platform-side Customer — destination charges require the
        # payment method to live on the platform (skeleton_02).
        customer = await stripe.Customer.create_async(
            name=attendee.name,
            phone=attendee.phone,
            metadata={"attendee_id": str(attendee.id)},
        )
        attendee.stripe_customer_id = customer.id
    intent = await stripe.SetupIntent.create_async(
        customer=attendee.stripe_customer_id,
        usage="off_session",
        payment_method_types=["card"],
        metadata={"attendee_id": str(attendee.id)},
    )
    return intent.client_secret


async def record_saved_card(
    attendee: Attendee, setup_intent_id: str
) -> Attendee:
    """Finalize the save once the browser confirms: retrieve the
    SetupIntent (never trust the client for the id), assert its
    status is 'succeeded', and persist
    attendee.stripe_payment_method_id."""
    if attendee.stripe_customer_id is None:
        raise ValueError(
            "attendee has no Stripe customer — no card save to "
            "finalize"
        )
    _configure()
    intent = await stripe.SetupIntent.retrieve_async(setup_intent_id)
    if intent.customer != attendee.stripe_customer_id:
        # A tampered id must not attach someone else's card.
        raise ValueError(
            "SetupIntent does not belong to this attendee"
        )
    if intent.status != "succeeded":
        raise CardSaveFailed(intent.status)
    attendee.stripe_payment_method_id = intent.payment_method
    return attendee


async def charge_share(
    payment: Payment,
    attendee: Attendee,
    planner: Planner,
    actual_cents: int,
) -> Payment:
    """Charge the saved card at close: Payment none -> paid, or
    none -> unpaid on a decline. Fires from `none` ONLY — the
    tap-to-pay link is the sole recovery from `unpaid`
    (decisions.md 2026-07-16). Off-session PaymentIntent
    (confirm=True, immediate capture, on_behalf_of and
    transfer_data.destination = planner), idempotency key
    "{payment.id}:charge". Record-first: the caller stamps
    charge_requested_at AND charge_requested_cents with the
    attendance change BEFORE this call; this refuses a missing
    stamp or a drifted amount, and writes the terminal state after
    Stripe answers. A declined PI is recorded on the row."""
    _validate_cents(actual_cents)
    if payment.state != "none":
        raise ValueError(
            "charge_share fires from 'none' only; the tap-to-pay "
            "link is the recovery from 'unpaid' (decisions.md "
            "2026-07-16)"
        )
    if payment.charge_requested_at is None:
        raise ValueError(
            "record-first: stamp charge_requested_at (+ cents) in "
            "the attendance transaction before moving money"
        )
    if payment.charge_requested_cents != actual_cents:
        raise ValueError(
            "amount drifted from the stamped intent — a retry must "
            "re-send exactly what was recorded (decisions.md "
            "2026-07-16)"
        )
    if (
        attendee.stripe_customer_id is None
        or attendee.stripe_payment_method_id is None
    ):
        raise ValueError(
            "attendee has no saved card — collect via the "
            "tap-to-pay link instead"
        )
    _configure()
    try:
        intent = await stripe.PaymentIntent.create_async(
            amount=actual_cents,
            currency="usd",
            customer=attendee.stripe_customer_id,
            payment_method=attendee.stripe_payment_method_id,
            confirm=True,
            off_session=True,
            on_behalf_of=planner.stripe_account_id,
            transfer_data={
                "destination": planner.stripe_account_id,
            },
            metadata={
                "payment_id": str(payment.id),
                "event_id": str(payment.event_id),
                "attendee_id": str(payment.attendee_id),
            },
            idempotency_key=f"{payment.id}:charge",
        )
    except stripe.CardError as err:
        # "The card said no" is an OUTCOME, not an error: record it
        # and open the tap-to-pay path. getattr throughout because a
        # malformed error payload must still land the row in
        # `unpaid`, never crash mid-bookkeeping.
        error_obj = getattr(err, "error", None)
        _move(payment, "unpaid")
        payment.state_reason = (
            getattr(error_obj, "decline_code", None)
            or err.code
            or "declined"
        )
        declined_pi = getattr(error_obj, "payment_intent", None)
        if declined_pi is not None:
            payment.stripe_payment_intent_id = declined_pi.id
        return payment
    if intent.status != "succeeded":
        # Never write `paid` for money that has not collected.
        # Dangling (stamp set, state `none`) is loud and safely
        # retryable with the same key.
        raise RuntimeError(
            f"PaymentIntent {intent.id} returned status "
            f"{intent.status!r}, not 'succeeded'"
        )
    _move(payment, "paid")
    payment.charged_cents = actual_cents
    payment.stripe_payment_intent_id = intent.id
    return payment


async def create_payment_link(
    payment: Payment, planner: Planner, actual_cents: int
) -> str:
    """Cardless / post-decline: open a one-time Checkout Session for
    the share (mode='payment', Connect wiring under
    payment_intent_data) and return its URL for the planner to text.
    `unpaid` rows only. One payable link per row (decisions.md
    2026-07-16): an already-stored session is retired first —
    refused if it collected (poll must reconcile), expired if still
    open. Store session.id on payment.stripe_checkout_session_id so
    poll_link_status can read it. Do NOT pin a fixed idempotency key
    — a session expires and a reused key replays the dead one. No
    success_url: Stripe's hosted confirmation page suffices in v0."""
    _validate_cents(actual_cents)
    if payment.state != "unpaid":
        raise ValueError(
            "a tap-to-pay link is minted for 'unpaid' rows only"
        )
    _configure()
    old_id = payment.stripe_checkout_session_id
    if old_id is not None:
        # One payable link per row (decisions.md 2026-07-16): a
        # replaced link must die first, and a collected one must be
        # reconciled by the poller, never papered over.
        old = await stripe.checkout.Session.retrieve_async(old_id)
        if old.payment_status == "paid":
            raise ValueError(
                "old link already collected — run poll_link_status "
                "before re-minting"
            )
        if old.status == "open":
            await stripe.checkout.Session.expire_async(old_id)
    session = await stripe.checkout.Session.create_async(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": actual_cents,
                    "product_data": {"name": "Your share"},
                },
                "quantity": 1,
            }
        ],
        payment_intent_data={
            "on_behalf_of": planner.stripe_account_id,
            "transfer_data": {
                "destination": planner.stripe_account_id,
            },
        },
        metadata={
            "payment_id": str(payment.id),
            "event_id": str(payment.event_id),
            "attendee_id": str(payment.attendee_id),
        },
    )
    payment.stripe_checkout_session_id = session.id
    return session.url


async def poll_link_status(payment: Payment) -> Payment:
    """Roster-load reconciliation (option b, no webhook —
    decisions.md 2026-07-15): retrieve the Checkout Session and, if
    payment_status == 'paid', move unpaid -> paid, record
    charged_cents + the collecting PaymentIntent id (overwrites a
    recorded decline PI — latest charge attempt), and clear
    state_reason. No Stripe call unless the row is `unpaid` with a
    stored session id. NOTE for the future abandon action: expire
    any open link when abandoning, or a late payment on it would go
    unseen by this guard."""
    if (
        payment.state != "unpaid"
        or payment.stripe_checkout_session_id is None
    ):
        return payment
    _configure()
    session = await stripe.checkout.Session.retrieve_async(
        payment.stripe_checkout_session_id
    )
    if session.payment_status != "paid":
        return payment
    _move(payment, "paid")
    payment.charged_cents = session.amount_total
    payment.stripe_payment_intent_id = session.payment_intent
    # The decline/no-card reason is history once collected.
    payment.state_reason = None
    return payment


async def refund_charge(payment: Payment, refund_cents: int) -> Payment:
    """Reverse a COLLECTED charge: paid -> refunded. Full or partial
    (the walk-in overage). MUST pass reverse_transfer=True so the
    money comes back from the planner's balance, not the platform's.
    Deferred in v0 (ships with walk-ins). When writing the body, the
    edit that adds the Refund API call must ALSO carry the marker
    'refund-guard: captured-only' and assert state == 'paid', or
    money_guard.py denies it."""
    raise NotImplementedError("author with review — CLAUDE.md")
