"""One-off: what does Stripe's fee ACTUALLY round to at the cent boundary?

Settles the open gross_up question (tests/test_fees.py, the $30 pin):
is Stripe's fee on a $31.20 charge 20c (round-half-up) or 21c
(round-up)? Our model (app/fees.py fee_cents) rounds the 2.9% part
half-up, so it predicts 20c and makes $31.20 the minimal make-whole
charge. The empirical ledger ($40->$1.46, $32->$1.23) never hit a
value that distinguishes half-up from round-up — this does.

TEST MODE ONLY. Refuses a live key: it creates real charges otherwise.
Test-mode charges carry the same fee schedule your ledger was built
from, so this costs nothing. The rounding is the same whether or not
Connect wiring is present, so these are plain platform charges — no
connected account needed.

Run:

    STRIPE_SECRET_KEY=sk_test_... .venv/bin/python skeleton_03_fee_rounding.py

Then report the 3120 row's fee: 120 or 121.
"""
import os
import sys

import stripe

PCT_BPS, FIXED = 290, 30

# (amount_cents, what it probes)
PROBES = [
    (1000, "sanity  2.9%=29.00 exact          -> 59  (any rounding)"),
    (3200, "sanity  2.9%=92.80                 -> 123 (models agree)"),
    (4000, "sanity  2.9%=116.00                -> 146"),
    (1010, "SPLIT   2.9%=29.29  half-up 29 / round-up 30"),
    (3120, "THE PIN 2.9%=90.48  half-up 90=fee120 / round-up 91=fee121"),
    (500,  "EXACT ½ 2.9%=14.50  half-up 15 / half-even 14"),
]


def half_up(c: int) -> int:
    """What app/fees.py fee_cents predicts."""
    return (c * PCT_BPS + 5_000) // 10_000 + FIXED


def round_up(c: int) -> int:
    """The ceil alternative the $30 pin (3121) assumes."""
    return -(-c * PCT_BPS // 10_000) + FIXED


def main() -> None:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        sys.exit("set STRIPE_SECRET_KEY=sk_test_... first")
    if not key.startswith("sk_test_"):
        # Fail closed: a live key here would place real charges.
        sys.exit(
            "refusing to run: needs a TEST key (sk_test_...). "
            "A live key would create real charges."
        )
    stripe.api_key = key

    print(f"{'amount':>7} {'stripe':>7} {'half_up':>8} {'round_up':>9}  verdict")
    print("-" * 60)
    pin_fee: int | None = None
    for cents, note in PROBES:
        try:
            pi = stripe.PaymentIntent.create(
                amount=cents,
                currency="usd",
                payment_method="pm_card_visa",
                payment_method_types=["card"],
                confirm=True,
            )
            charge = stripe.Charge.retrieve(
                pi.latest_charge, expand=["balance_transaction"]
            )
            fee = charge.balance_transaction.fee
        except Exception as err:  # keep probing the rest
            print(f"{cents:>7}  ERROR: {err}")
            continue
        hu, ru = half_up(cents), round_up(cents)
        verdict = (
            "half-up" if fee == hu
            else "round-up" if fee == ru
            else "NEITHER"
        )
        print(f"{cents:>7} {fee:>7} {hu:>8} {ru:>9}  {verdict}   {note}")
        if cents == 3120:
            pin_fee = fee

    print("-" * 60)
    if pin_fee == 120:
        print("VERDICT: fee 120 -> half-up is right. Pin -> 3120; "
              "fee_cents stays; I write gross_up.")
    elif pin_fee == 121:
        print("VERDICT: fee 121 -> Stripe rounds UP here. fee_cents "
              "must change before gross_up; the 3121 pin stands.")
    else:
        print(f"VERDICT: unexpected 3120 fee ({pin_fee!r}) — send me the table.")


if __name__ == "__main__":
    main()
