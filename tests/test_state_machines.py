"""Table-driven contract tests for state_machines.py.

LEGAL below is a second, independent transcription of
state_machines.md — if the module and this file ever disagree,
one of them drifted from the doc and the tests fail. Everything
outside LEGAL (full cross-product of documented states) must be
rejected.
"""
import pytest

from app.state_machines import (
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
    ("rsvp", "going", "attended"),
    ("rsvp", "going", "no_show"),
    # uniform rule (decisions.md 2026-07-21): any answer to any
    # answer while the event is open
    ("rsvp", "going", "maybe"),
    ("rsvp", "going", "declined"),
    ("rsvp", "maybe", "going"),
    ("rsvp", "maybe", "declined"),
    ("rsvp", "declined", "going"),
    ("rsvp", "declined", "maybe"),
    # Payment — charge-at-close (decisions.md 2026-07-15)
    ("payment", "none", "paid"),
    ("payment", "none", "unpaid"),
    ("payment", "unpaid", "paid"),
    ("payment", "unpaid", "abandoned"),
    ("payment", "paid", "refunded"),
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
        "rsvp": {"attended", "no_show"},
        "payment": {
            "refunded",
            "abandoned",
        },
        "attendance": {"present", "absent"},
    }
    for name, states in terminals.items():
        for state in states:
            assert MACHINES[name][state] == set()


class TestMoneyInvariants:
    """Transitions whose absence IS the money model — each maps to
    a NON-NEGOTIABLE rule in CLAUDE.md / decisions.md
    (charge-at-close, 2026-07-15)."""

    def test_no_refund_of_uncollected_money(self) -> None:
        # Refund reverses money actually collected; an unpaid or
        # never-charged share has nothing to send back.
        assert not can_transition(PAYMENT, "unpaid", "refunded")
        assert not can_transition(PAYMENT, "none", "refunded")

    def test_no_silent_uncharge(self) -> None:
        # Once paid, money only flows back via refund — a charge is
        # never quietly downgraded to unpaid or none.
        assert not can_transition(PAYMENT, "paid", "unpaid")
        assert not can_transition(PAYMENT, "paid", "none")

    def test_abandoned_is_terminal(self) -> None:
        # Giving up is final; collecting later is a NEW attempt row
        # (decisions.md 2026-07-08), not a move out of abandoned.
        assert PAYMENT["abandoned"] == set()
