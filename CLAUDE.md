# KnowaPlan — CLAUDE.md

## What this is
Web app: attendees optionally save a card at RSVP; the organizer
charges each person's actual share after the event — from the saved
card, or via a tap-to-pay link (charge-at-close, no holds —
decisions.md 2026-07-15). v0 = pickleball court splits, one metro
area, one known group. Custodies real money — correctness over speed.

## Stack
- Python 3.12.3 (.venv), FastAPI, Pydantic v2
- Postgres
- Stripe Connect (Standard), destination charges with
  on_behalf_of=planner; charge-at-close, no holds (decisions.md
  2026-07-15): card saved at RSVP (SetupIntent) or a tap-to-pay link
- Reminders sent from the planner's own phone (native Messages,
  pre-filled) — no Twilio in v0 (decisions.md 2026-07-15); .ics for
  calendar
- Web-first, no native app for v0
- No accounts in v0: capability URLs — event link, per-attendee RSVP
  link, planner admin link (decisions.md 2026-07-13)

## Canonical docs — read before any architectural change
- @decisions.md       append-only architectural decisions
- @state_machines.md  Event / RSVP / Payment / Attendance contracts
- @scenarios.md       user-facing edge-case behaviors
If a change would contradict any of these, stop and ask.
## Commands
- Run app:       .venv/bin/uvicorn app.main:app --reload
- Create tables: .venv/bin/python -m app.bootstrap (create_all
  only — after a model change, drop/recreate the dev DB, re-run)
- Run skeleton:  python skeleton_02_payment.py (hold-era proof;
  see its header note)
- Tests:         .venv/bin/pytest
- Lint/format:   .venv/bin/ruff check . / .venv/bin/ruff format .
- Dev deps:      pinned in requirements-dev.txt

## Money-handling rules (NON-NEGOTIABLE)
- All amounts in integer cents. Never float.
- No card holds in v0 (decisions.md 2026-07-15): charge the actual
  share at close — from a card saved at RSVP, or a tap-to-pay link. A
  card saved at RSVP is a SetupIntent, not an authorization; no money
  moves until close.
- Payment is NOT guaranteed: a saved card can decline off-session, a
  cardless attendee can ghost the link. Surface unpaid balances on the
  roster; never assume collected.
- Actual > estimate: the planner chooses charge-actual or
  cap-and-absorb; DEFAULT (incl. auto-settle) is charge the actual
  share. Silence never triggers the planner absorbing.
- Refund = reversing an already-collected charge, only.
- Every charge uses an idempotency key derived from (payment.id,
  operation): a retry after a blip reuses its key; a genuinely new
  attempt is a new row with a fresh key.
- A charge and its matching attendance update happen together,
  record-first: one DB transaction writes the attendance change AND a
  charge-requested stamp BEFORE the Stripe call; the terminal state is
  written after. A dangling charge is queryable and retried with the
  SAME idempotency key. The DB must always know at least as much as
  Stripe.
- Revisit trigger: reintroduce holds when opening to strangers or
  charging amounts where a single decline hurts.

### Money guard (enforced, not advisory)
A PreToolUse hook (.claude/hooks/money_guard.py, wired via
.claude/settings.json) denies any .py edit that uses the Refund API
without the marker `refund-guard: captured-only`. Refund stays
reversal-of-a-collected-charge only, so that guard survives the
2026-07-15 pivot. The hook's old auth-expiry / settle-offset guard
was retired with the pivot (no holds to expire); settle-scheduling
edits are no longer denied. The guard fails closed; its behavior is
pinned by tests/test_money_guard.py.

## Code style
- Type hints on every function signature.
- Async for anything touching the DB or Stripe.
- Comments explain WHY, not WHAT.
- Keep lines narrow — no horizontal scroll.

## How to work here
- Payment and state-machine code is load-bearing: explain the
  mechanism and let me review or write it. Do not author it wholesale.
  app/payments.py exposes the charge-at-close surface (setup-intent
  save, charge_share, payment link + poll, refund) as stubs whose
  bodies raise NotImplementedError — they get written with owner
  review, mechanism documented in each docstring.
- Never call the live Stripe API in tests — use test tokens / a mock.
- Align before acting (owner instruction, 2026-07-16): every design
  or shaping decision — behavior, contracts, docs, schema, process,
  names, defaults, wording — is put to the owner with a
  recommendation BEFORE any file changes. Design forks one at a
  time; independent shaping details as a numbered list. A step
  opens with the full walkthrough (mechanism, exact body draft,
  test list, shaping list); files change only after alignment.
  Mechanics of an approved step (running tests, applying the
  previewed edit, its commit/push) proceed under that approval.
  If a turn ends mid-step, checkpoint suite-green (pending tests
  xfail strict=true, unwritten bodies still raising) and say
  what is pending.
- Explanations are written for a junior developer (owner
  instruction, 2026-07-16): plain language, define terms,
  concrete scenarios over abstractions — in walkthroughs,
  grilling sessions, and step reports alike.