"""Executable transcription of state_machines.md.

Pure data: each machine maps a state to the set of states it may
legally transition to. Terminal states map to the empty set. The
tables carry no behavior — services consult them so an illegal
transition can never be a silent typo. If a table here disagrees
with state_machines.md, the doc wins; fix the table.
"""

# Event: draft → open → closed → settled → archived, with
# cancellation possible until settlement.
EVENT: dict[str, set[str]] = {
    "draft": {"open"},
    "open": {"closed", "cancelled"},
    "closed": {"settled", "cancelled"},
    "settled": {"archived"},
    "archived": set(),
    "cancelled": set(),
}

# RSVP: a card on file is OPTIONAL and tracked on the Payment row,
# not here (charge-at-close, decisions.md 2026-07-15) — so `going`
# goes straight to attended/no_show, with no going_paid gate.
# Uniform rule (decisions.md 2026-07-21): any answer to any answer
# — {going, maybe, declined} are mutually reachable. Every answer
# change is valid only while the Event is open — that guard lives
# in the service layer; this table has no event context.
# attended/no_show are the planner's writes at settlement.
RSVP: dict[str, set[str]] = {
    "pending": {"going", "maybe", "declined"},
    "going": {"maybe", "declined", "attended", "no_show"},
    "maybe": {"going", "declined"},
    "declined": {"going", "maybe"},
    "attended": set(),
    "no_show": set(),
}

# Payment: charge-at-close (decisions.md 2026-07-15) — no holds.
# The share is charged at close from a saved card (none → paid) or
# lands unpaid (no card, or an off-session decline) and is then
# collected via a tap-to-pay link (unpaid → paid) or given up on
# (unpaid → abandoned). refunded = reversal of a COLLECTED charge
# only. No authorized/voided/auth_failed/failed — those needed a
# hold, which the 2026-07-15 pivot removed.
PAYMENT: dict[str, set[str]] = {
    "none": {"paid", "unpaid"},
    "paid": {"refunded"},
    "unpaid": {"paid", "abandoned"},
    "refunded": set(),
    "abandoned": set(),
}

# Attendance: resolved once, at settlement (72h edit window is a
# re-mark of the same machine, not a new state).
ATTENDANCE: dict[str, set[str]] = {
    "unconfirmed": {"present", "absent"},
    "present": set(),
    "absent": set(),
}


def can_transition(
    machine: dict[str, set[str]], src: str, dst: str
) -> bool:
    """True if the machine allows src → dst. Unknown states allow
    nothing rather than raising — callers treat both the same way."""
    return dst in machine.get(src, set())
