"""Phone canonicalization — one spelling per person.

Identity in v0 IS the phone (no accounts — decisions.md
2026-07-13), and every lookup was exact-string: iOS autofill
"(619) 555-0123" vs typed digits minted a DUPLICATE attendee
(orphaning any saved card) and could miss the
never-charge-the-planner match — settle would then charge the
planner's own card. Canonical form: exactly 10 bare digits, US
country code stripped. Strict on purpose: a typo caught at the
form beats a wrong identity at settle, and v0 is one US metro.
"""


def normalize_phone(raw: str) -> str:
    digits = "".join(c for c in raw if "0" <= c <= "9")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError(
            "that phone number doesn't look right — use 10 "
            "digits, like 6195550123"
        )
    return digits
