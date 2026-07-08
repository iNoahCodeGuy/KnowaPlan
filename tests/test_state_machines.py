"""Table-driven contract tests for state_machines.py.

LEGAL below is a second, independent transcription of
state_machines.md — if the module and this file ever disagree,
one of them drifted from the doc and the tests fail. Everything
outside LEGAL (full cross-product of documented states) must be
rejected.
"""
import pytest

from state_machines import (
    ATTENDANCE,
    EVENT,
    PAYMENT,
    RSVP,
    can_transition,
)

MACHINES = {
    "event": EVENT,
    "rsvp": RSVP,
    "payment": PAYMENT,
    "attendance": ATTENDANCE,
}

LEGAL: set[tuple[str, str, str]] = {
    # Event
    ("event", "draft", "open"),
    ("event", "open", "closed"),
    ("event", "open", "cancelled"),
    ("event", "closed", "settled"),
    ("event", "closed", "cancelled"),
    ("event", "settled", "archived"),
    # RSVP
    ("rsvp", "pending", "going"),
    ("rsvp", "pending", "maybe"),
    ("rsvp", "pending", "declined"),
    ("rsvp", "going", "going_paid"),
    ("rsvp", "going_paid", "attended"),
    ("rsvp", "going_paid", "no_show"),
    ("rsvp", "maybe", "going"),
    ("rsvp", "maybe", "declined"),
    # Payment
    ("payment", "none", "authorized"),
    ("payment", "authorized", "captured"),
    ("payment", "authorized", "voided"),
    ("payment", "authorized", "failed"),
    ("payment", "captured", "refunded"),
    ("payment", "failed", "resolved"),
    ("payment", "failed", "abandoned"),
    # Attendance
    ("attendance", "unconfirmed", "present"),
    ("attendance", "unconfirmed", "absent"),
}

ALL_PAIRS = [
    (name, src, dst)
    for name, machine in MACHINES.items()
    for src in machine
    for dst in machine
]


@pytest.mark.parametrize(("name", "src", "dst"), sorted(LEGAL))
def test_documented_transitions_allowed(
    name: str, src: str, dst: str
) -> None:
    assert can_transition(MACHINES[name], src, dst)


@pytest.mark.parametrize(
    ("name", "src", "dst"),
    [p for p in ALL_PAIRS if p not in LEGAL],
)
def test_undocumented_transitions_rejected(
    name: str, src: str, dst: str
) -> None:
    assert not can_transition(MACHINES[name], src, dst)


def test_terminal_states_allow_nothing() -> None:
    terminals = {
        "event": {"archived", "cancelled"},
        "rsvp": {"declined", "attended", "no_show"},
        "payment": {"voided", "refunded", "resolved", "abandoned"},
        "attendance": {"present", "absent"},
    }
    for name, states in terminals.items():
        for state in states:
            assert MACHINES[name][state] == set()


class TestMoneyInvariants:
    """Transitions whose absence IS the money model — each maps to
    a NON-NEGOTIABLE rule in CLAUDE.md / decisions.md."""

    def test_no_refund_without_capture(self) -> None:
        # A release of an uncaptured hold is a void, never a refund
        assert not can_transition(PAYMENT, "authorized", "refunded")

    def test_no_void_after_capture(self) -> None:
        # Money moved; the only reversal of a capture is a refund
        assert not can_transition(PAYMENT, "captured", "voided")

    def test_walk_in_direct_charge_deferred_in_v0(self) -> None:
        # none → captured ships with walk-ins, not in v0
        assert not can_transition(PAYMENT, "none", "captured")
