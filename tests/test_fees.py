"""Pins the gross-up money math (NOTES.md checkpoint; shaping
calls confirmed 2026-07-18). Written RED first: the bodies in
app/fees.py are owner-authored against these tests.

xfail(strict=True) keeps the suite green while the bodies still
raise — the moment a body lands, the unexpected pass fails the
suite loudly and the marker comes off with the implementation.

Constants mirror the empirical ledger: 2.9% (290 bps) rounded
half-up, plus 30c fixed.
"""

import pytest

from app.config import get_settings
from app.fees import fee_cents, gross_up

PCT_BPS = 290
FIXED = 30

pending = pytest.mark.xfail(
    strict=True,
    reason="gross_up step: owner authors the bodies "
    "(NOTES.md checkpoint, 2026-07-18)",
)


def test_fee_model_matches_recorded_ledger() -> None:
    # Real charges off the real account (RESOURCES.md, verified
    # 2026-07-16): $40.00 -> $1.46 and $32.00 -> $1.23, exact.
    assert fee_cents(4_000, PCT_BPS, FIXED) == 146
    assert fee_cents(3_200, PCT_BPS, FIXED) == 123
    # The grossed $30 share: $31.21 -> $1.21 (92.8 -> 93 was the
    # half-up example in the old note; this one is 90.509 -> 91).
    assert fee_cents(3_121, PCT_BPS, FIXED) == 121


@pending
def test_gross_up_known_values() -> None:
    # $30.00 share bills $31.21 and nets exactly $30.00. $40.00
    # bills $41.50 — the rejected ceil-only draft said $41.51,
    # one cent over (NOTES.md correction, 2026-07-18).
    assert gross_up(3_000, PCT_BPS, FIXED) == 3_121
    assert gross_up(4_000, PCT_BPS, FIXED) == 4_150


@pending
def test_gross_up_make_whole_and_minimal_every_cent() -> None:
    """The property that IS the definition, for every share from
    1c to $500.00: the billed amount nets exactly the share
    (make-whole; on this fee model minimal implies exact), and
    one cent less would under-net the planner (minimal)."""
    for share in range(1, 50_001):
        billed = gross_up(share, PCT_BPS, FIXED)
        net = billed - fee_cents(billed, PCT_BPS, FIXED)
        assert net == share
        one_less = (billed - 1) - fee_cents(billed - 1, PCT_BPS, FIXED)
        assert one_less < share


@pending
def test_gross_up_nothing_owed_bills_nothing() -> None:
    assert gross_up(0, PCT_BPS, FIXED) == 0


@pending
def test_rate_is_config_held() -> None:
    # Shaping call 1: a Stripe rate change is a deploy (env var),
    # never a code edit.
    settings = get_settings()
    assert settings.stripe_pct_bps == 290
    assert settings.stripe_fixed_cents == 30
