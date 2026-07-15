#!/usr/bin/env python3
"""PreToolUse guard for KnowaPlan's money invariant.

Refund guard — a Refund may only reverse an already-collected
charge (Payment state `paid`). Under charge-at-close there is no
hold to void and no uncaptured overage to release, so a Refund is
the ONLY way money flows back — and it must never run against a
charge that was never collected. New code touching the Refund API
must carry the marker "refund-guard: captured-only" to show the
author checked the payment is collected before refunding.

The old scheduler guard (auto-settle bounded by authorization
expiry) was RETIRED in the 2026-07-15 pivot: no holds means no auth
expiry to bound. See decisions.md 2026-05-28 (original) and
2026-07-15 (retirement).

Reads the hook payload JSON from stdin; prints a PreToolUse deny
decision and exits 0 when the invariant is violated, otherwise
prints nothing (allow).
"""
import json
import re
import sys

# Actual Refund API usage only — prose mentions of "refund" in
# comments, docstrings, or state names must not trip the guard.
REFUND_API = re.compile(
    r"stripe\.Refund"
    r"|Refund\.create"
    r"|\brefunds\.create"
    r"|/v1/refunds"
    r"|from\s+stripe(?:\.\S+)?\s+import\s+[^\n]*\bRefund\b"
)
REFUND_ACK = "refund-guard: captured-only"


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main() -> None:
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input", {})
    path = tool_input.get("file_path", "")

    # Only Python source moves money; docs may discuss refunds
    # freely, and the guard must not block edits to itself.
    if not path.endswith(".py") or "/.claude/" in path:
        return

    # Gather every field that can carry new code, including a
    # MultiEdit-style edits array.
    parts = [
        tool_input.get("content") or "",
        tool_input.get("new_string") or "",
    ]
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict):
            parts.append(edit.get("new_string") or "")
    text = "\n".join(parts)

    if REFUND_API.search(text) and REFUND_ACK not in text:
        deny(
            "Money invariant (decisions.md 2026-07-15): a Refund may only "
            "reverse an already-collected charge (Payment state 'paid'). "
            "Charge-at-close has no hold to void and no overage to "
            "release, so a Refund is the only way money flows back. If "
            "this genuinely refunds a collected charge, assert the "
            f"payment state is 'paid' and include the marker '{REFUND_ACK}' "
            "in the same edit."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        # Money guard fails CLOSED: a broken guard must not wave
        # payment code through silently.
        deny(f"money_guard.py errored ({exc!r}); fix the guard or "
             "the payload before editing payment code.")
