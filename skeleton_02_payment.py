"""
Walking skeleton, step 2: prove the full Stripe payment plumbing.

Flow:
  1. Create a Customer (the attendee)
  2. Authorize $40 worst-case using a test payment token (the RSVP moment)
  3. Capture $32 actual share (the post-attendance moment)
  4. Verify $8 is released automatically — no refund issued

Data structures:
  - stripe.Customer      — attendee identity + card on file
  - stripe.PaymentIntent — tracks the full payment lifecycle

Rule: all amounts in cents (int). Never float.
"""

import os
from dotenv import load_dotenv
import stripe

load_dotenv()

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
planner_account_id = os.environ["TEST_PLANNER_ACCOUNT_ID"]

# Amounts in cents — int only, never float (float math loses pennies)
WORST_CASE_AMOUNT = 4000   # $40.00 — authorized at RSVP
ACTUAL_SHARE      = 3200   # $32.00 — captured after attendance confirmed

# ── Step 1: Create a Customer on the platform account ─────────────────────
# The Customer MUST live on the platform, not the connected account.
# Destination charges require the payment method to belong to a
# platform Customer — this is a Stripe constraint, not our choice.
customer = stripe.Customer.create(
    email="test-attendee@example.com",
    name="Test Attendee",
    metadata={"note": "skeleton test — safe to delete"}
)
print(f"[1] Customer:          {customer.id}")

# ── Step 2: Create + Confirm the PaymentIntent (the RSVP moment) ──────────
# pm_card_visa is Stripe's built-in test token — it represents what
# the Payment Element hands your server in production. Raw card numbers
# never touch your server; the client-side Payment Element handles
# card collection and returns a token like this one.
#
# capture_method="manual"
#   → hold the authorization; we decide when to capture
#
# on_behalf_of=planner_account_id
#   → planner is merchant of record; their name appears on
#     the attendee's bank statement, not "KnowaPlan"
#
# transfer_data.destination=planner_account_id
#   → after capture, funds flow to planner's Stripe account
#
# confirm=True
#   → authorize the card immediately on creation
#
# Note: Extended Authorization (30-day capture window) is deferred —
# it requires Stripe IC+ pricing. We rely on the default 7-day window.
# See decisions.md (2026-05-26).
intent = stripe.PaymentIntent.create(
    amount=WORST_CASE_AMOUNT,
    currency="usd",
    customer=customer.id,
    payment_method="pm_card_visa",     # Stripe's built-in test token
    capture_method="manual",           # hold auth, capture later
    confirm=True,                      # authorize the card now
    on_behalf_of=planner_account_id,   # planner = merchant of record
    transfer_data={
        "destination": planner_account_id,   # funds go to planner
    },
    
    return_url="https://example.com",  # required when confirm=True
)

print(f"[2] PaymentIntent:     {intent.id}")
print(f"    Status:            {intent.status}")
print("    Expected:          requires_capture")

# ── Step 3: Capture the actual share (the post-attendance moment) ─────────
# Planner has marked attendance. We capture only the actual per-person
# cost. Stripe releases the uncaptured $8 automatically — it never
# appears as a charge on the attendee's statement.
captured = stripe.PaymentIntent.capture(
    intent.id,
    amount_to_capture=ACTUAL_SHARE,
)

print(f"\n[3] Status after capture: {captured.status}")
print("    Expected:             succeeded")
print(f"\n    Authorized:  ${WORST_CASE_AMOUNT / 100:.2f}")
print(f"    Captured:    ${ACTUAL_SHARE / 100:.2f}")
print(f"    Released:    ${(WORST_CASE_AMOUNT - ACTUAL_SHARE) / 100:.2f}")
print("\n    Check Stripe dashboard → Payments to verify the charge.")
print("    Check Connect → Transfers to verify funds reached the planner.")