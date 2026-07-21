"""Stripe-fee gross-up — attendees cover the fee.

Owner decision (2026-07-16, shaped 2026-07-18): bill each attendee
a grossed-up amount sized so that after Stripe's cut the planner
nets the exact share. The fee model is pinned empirically against
the real ledger (stripe.com/pricing; $40.00 -> $1.46, $32.00 ->
$1.23, both exact): round-half-up(2.9% of the charge) + 30 cents.
Stripe's rounding at an exact half-cent is UNVERIFIED (NOTES.md);
our model rounds half up.

Both functions are pure and integer-only (money rule: cents, never
float). The rate arrives as arguments — config holds it (shaping
call 1), tests need no env. Bodies are owner-authored against
tests/test_fees.py (CLAUDE.md: money code is not authored
wholesale).
"""


def fee_cents(charge_cents: int, pct_bps: int, fixed_cents: int) -> int:
    """Stripe's fee on a charge, in cents.

    Round-half-up on the percentage part — in integers:
    (charge_cents * pct_bps + 5_000) // 10_000 — then the fixed
    part on top.
    """
    percentage = (charge_cents * pct_bps + 5_000) // 10_000
    return percentage + fixed_cents


def gross_up(share_cents: int, pct_bps: int, fixed_cents: int) -> int:
    """The SMALLEST charge c with c - fee_cents(c) >= share_cents.

    Make-whole AND minimal. The net (c - fee(c)) rises in 0-or-1
    cent steps, so the minimal make-whole charge nets EXACTLY the
    share. A ceil-inversion alone is not enough — it never
    under-collects, but over-collects +1c on ~51% of share values
    (NOTES.md, corrected 2026-07-18); use it as a first guess,
    then walk down (and, defensively, up) to the exact answer.
    Nothing owed bills nothing: share <= 0 returns 0.
    """
    raise NotImplementedError  # owner writes the body
