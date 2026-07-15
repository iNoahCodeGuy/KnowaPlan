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
- Record-first: charge_share stamps payment.charge_requested_at in
  the same DB transaction as the attendance change, BEFORE the
  Stripe call; the terminal state (paid/unpaid) is written after. A
  dangling charge (stamp set, state still `none`) is queryable and
  retried with the SAME idempotency key. The DB must always know at
  least as much as Stripe.
- Never call the live Stripe API in tests — inject a mock (conftest
  mock_stripe).
"""
from app.models import Attendee, Payment


async def create_setup_intent(attendee: Attendee) -> str:
    """Save a card at RSVP: create a SetupIntent on the platform
    Customer (creating the Customer first if needed) and return its
    client_secret for the browser's Payment Element. Moves no money;
    usage="off_session" so any 3DS runs on-session, now."""
    raise NotImplementedError("author with review — CLAUDE.md")


async def record_saved_card(
    attendee: Attendee, setup_intent_id: str
) -> Attendee:
    """Finalize the save once the browser confirms: retrieve the
    SetupIntent (never trust the client for the id), assert its
    status is 'succeeded', and persist
    attendee.stripe_payment_method_id."""
    raise NotImplementedError("author with review — CLAUDE.md")


async def charge_share(payment: Payment, actual_cents: int) -> Payment:
    """Charge the saved card at close: Payment none -> paid, or
    none -> unpaid on a decline. Off-session PaymentIntent
    (confirm=True, immediate capture, on_behalf_of and
    transfer_data.destination = planner), idempotency key
    "{payment.id}:charge". Record-first: the caller stamps
    charge_requested_at with the attendance change BEFORE this call;
    this writes the terminal state after Stripe answers."""
    raise NotImplementedError("author with review — CLAUDE.md")


async def create_payment_link(
    payment: Payment, actual_cents: int
) -> str:
    """Cardless / post-decline: open a one-time Checkout Session for
    the share (mode='payment', Connect wiring under
    payment_intent_data) and return its URL for the planner to text.
    Store session.id on payment.stripe_checkout_session_id so
    poll_link_status can read it. Do NOT pin a fixed idempotency key
    — a session expires and a reused key replays the dead one."""
    raise NotImplementedError("author with review — CLAUDE.md")


async def poll_link_status(payment: Payment) -> Payment:
    """Roster-load reconciliation (option b, no webhook —
    decisions.md 2026-07-15): retrieve the Checkout Session and, if
    payment_status == 'paid', move unpaid -> paid and record
    charged_cents + the PaymentIntent id. A no-op once paid."""
    raise NotImplementedError("author with review — CLAUDE.md")


async def refund_charge(payment: Payment, refund_cents: int) -> Payment:
    """Reverse a COLLECTED charge: paid -> refunded. Full or partial
    (the walk-in overage). MUST pass reverse_transfer=True so the
    money comes back from the planner's balance, not the platform's.
    Deferred in v0 (ships with walk-ins). When writing the body, the
    edit that adds the Refund API call must ALSO carry the marker
    'refund-guard: captured-only' and assert state == 'paid', or
    money_guard.py denies it."""
    raise NotImplementedError("author with review — CLAUDE.md")
