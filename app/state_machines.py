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

# RSVP: going_paid is reached only via a successful authorization.
# Note: scenarios.md lets a declined attendee tap "Going" again
# before the event closes, but state_machines.md defines no
# declined → going transition — unresolved, doc wins for now.
RSVP: dict[str, set[str]] = {
    "pending": {"going", "maybe", "declined"},
    "going": {"going_paid"},
    "going_paid": {"attended", "no_show"},
    "maybe": {"going", "declined"},
    "declined": set(),
    "attended": set(),
    "no_show": set(),
}

# Payment: capturing less than authorized RELEASES the remainder
# (not a refund); voided = released without capture; refunded =
# reversal of a captured charge only. Walk-in direct charge
# (none → captured) is deferred in v0 — deliberately absent.
PAYMENT: dict[str, set[str]] = {
    "none": {"authorized"},
    "authorized": {"captured", "voided", "failed"},
    "captured": {"refunded"},
    "failed": {"resolved", "abandoned"},
    "voided": set(),
    "refunded": set(),
    "resolved": set(),
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
