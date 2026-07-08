"""Payment operations — MECHANISM DOCUMENTED, BODIES UNWRITTEN.

Per CLAUDE.md, money-moving code is authored or reviewed by the
project owner; these stubs pin down the contracts and the Stripe
mechanism so the bodies can be filled in deliberately. skeleton_02
is the proven reference for the create/capture calls.

Mechanism (proven in skeleton_02_payment.py):
- Authorize: PaymentIntent.create with capture_method="manual",
  confirm=True, on_behalf_of=<planner acct> and
  transfer_data.destination=<planner acct>. This places a hold
  for the worst-case share; no money moves yet. The hold dies
  7 days later (Extended Authorization deferred) — record
  auth_expires_at from the Stripe response.
- Capture: PaymentIntent.capture with amount_to_capture set to
  the ACTUAL share (<= authorized). Stripe releases the
  uncaptured remainder on the card network automatically — that
  release is NOT a refund and produces no Refund object.
- Void: PaymentIntent.cancel on an uncaptured authorization
  (no-show, removed pre-capture, event cancelled, expiry race).
- Refund (not stubbed here on purpose): only ever reverses an
  already-captured charge. There is no happy-path refund.

Invariants every body must keep:
- Amounts are integer cents.
- Every create/capture call passes an idempotency_key derived
  from (payment.id, operation). Stripe replays the original
  response for a reused key (~24h), so a key must never span two
  distinct attempts: re-authorizing an attendee voided earlier
  the same day is a NEW Payment row (next attempt) and therefore
  a fresh key, while retrying the SAME operation after a network
  blip reuses its key on purpose so it cannot double-charge.
- A capture and its matching attendance update commit together
  or not at all (one DB transaction around both).
"""
from app.models import Payment


async def authorize_hold(
    payment: Payment, worst_case_cents: int
) -> Payment:
    """Place the RSVP hold: Payment none → authorized."""
    raise NotImplementedError("author with review — CLAUDE.md")


async def capture_actual_share(
    payment: Payment, actual_cents: int
) -> Payment:
    """Charge the actual share: Payment authorized → captured.

    actual_cents must be <= payment.authorized_cents; the
    difference is released by Stripe, not refunded. Must run
    inside the same transaction as the attendance update.
    """
    raise NotImplementedError("author with review — CLAUDE.md")


async def void_authorization(
    payment: Payment, reason: str
) -> Payment:
    """Release the hold without capturing: authorized → voided."""
    raise NotImplementedError("author with review — CLAUDE.md")
