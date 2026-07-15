"""The PreToolUse money guard is itself money-invariant code —
pin its behavior like any other. Each case runs the real script
as a subprocess with the hook's stdin contract."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).parent.parent / ".claude/hooks/money_guard.py"
PY = "/Users/x/KnowaPlan/payments.py"
ACK = "refund-guard: captured-only"


def run_guard(payload: dict | str) -> str | None:
    """Return the deny reason, or None if the edit was allowed."""
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=raw,
        capture_output=True,
        text=True,
    )
    if not proc.stdout.strip():
        return None
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    return out["permissionDecisionReason"]


def write(path: str, content: str) -> dict:
    return {"tool_name": "Write",
            "tool_input": {"file_path": path, "content": content}}


DENIED = [
    write(PY, "stripe.Refund.create(charge=ch)"),
    write(PY, "client.refunds.create(charge=ch)"),
    write(PY, 'requests.post("https://api.stripe.com/v1/refunds")'),
    write(PY, "from stripe import Refund as R\nR.create()"),
    # MultiEdit-style edits array is scanned too
    {"tool_name": "Edit", "tool_input": {"file_path": PY, "edits": [
        {"new_string": "stripe.Refund.create(charge=ch)"}]}},
]

ALLOWED = [
    # acknowledged refund of a COLLECTED charge (state paid)
    write(PY, f"# {ACK}\nassert p.state == 'paid'\n"
              "stripe.Refund.create(charge=ch)"),
    # state names and prose are not API usage
    write(PY, 'state = "refunded"  # terminal'),
    # docs may discuss the Refund API freely
    write("/Users/x/KnowaPlan/decisions.md",
          "never stripe.Refund.create on uncollected"),
    # settle scheduling is no longer guarded — the auth-expiry
    # backstop was retired with holds (decisions.md 2026-07-15)
    write(PY, "backstop = event.end + timedelta(hours=24)"),
    # the guard must not block edits to itself
    write("/Users/x/KnowaPlan/.claude/hooks/money_guard.py",
          "stripe.Refund.create"),
]


@pytest.mark.parametrize("payload", DENIED)
def test_denied(payload: dict) -> None:
    assert run_guard(payload) is not None


@pytest.mark.parametrize("payload", ALLOWED)
def test_allowed(payload: dict) -> None:
    assert run_guard(payload) is None


def test_fails_closed_on_garbage_input() -> None:
    # A broken guard must never wave payment code through
    reason = run_guard("not json{")
    assert reason is not None and "errored" in reason
