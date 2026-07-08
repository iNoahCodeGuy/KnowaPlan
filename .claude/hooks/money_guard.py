#!/usr/bin/env python3
"""PreToolUse guard for KnowaPlan's money invariants.

Enforces the two "Hook, not prose" decisions in decisions.md
(2026-05-28):

1. Refund guard — a Refund may only reverse an already-captured
   charge. Capture-less paths must capture less than the hold or
   void the authorization, never refund. New code touching the
   Refund API must carry the marker "refund-guard: captured-only"
   to show the author checked the payment state is `captured`.

2. Scheduler guard — the auto-settle backstop must be bounded by
   the earliest authorization expiry, never a fixed post-event
   offset alone (auths expire 7 days after creation).

Reads the hook payload JSON from stdin; prints a PreToolUse deny
decision and exits 0 when an invariant is violated, otherwise
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

# "settl" over-triggers on purpose (settle, settling, settlement);
# a silent miss costs money, a spurious deny costs a marker.
SETTLE_CODE = re.compile(r"settl|backstop", re.IGNORECASE)
FIXED_OFFSET = re.compile(r"timedelta\s*\(")
EXPIRY = re.compile(r"expir", re.IGNORECASE)


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
            "Money invariant (decisions.md 2026-05-28): a Refund may only "
            "reverse an already-captured charge. Capture-less paths must "
            "capture (amount < hold) or void the authorization — never "
            "refund. If this code genuinely refunds a captured charge, "
            "assert the payment state is 'captured' and include the "
            f"marker '{REFUND_ACK}' in the same edit."
        )

    if (
        SETTLE_CODE.search(text)
        and FIXED_OFFSET.search(text)
        and not EXPIRY.search(text)
    ):
        deny(
            "Money invariant (decisions.md 2026-05-28): the auto-settle "
            "backstop is min(planner's settle target, earliest auth "
            "expiry across attendees) — never a fixed post-event offset "
            "alone. Auths expire 7 days after creation; a backstop past "
            "expiry silently loses the capture. Reference auth expiry in "
            "this scheduling code."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        # Money guard fails CLOSED: a broken guard must not wave
        # payment code through silently.
        deny(f"money_guard.py errored ({exc!r}); fix the guard or "
             "the payload before editing payment code.")
