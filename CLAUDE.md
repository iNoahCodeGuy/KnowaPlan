# KnowaPlan — CLAUDE.md

## What this is
Web app: organizer authorizes attendees' cards at RSVP, captures each
person's actual share after the event. v0 = pickleball court splits,
one metro area, one known group. Custodies real money — correctness
over speed.

## Stack
- Python 3.12.3 (.venv), FastAPI, Pydantic v2
- Postgres
- Stripe Connect (Standard), destination charges with
  on_behalf_of=planner; PaymentIntents, manual capture
- Twilio SMS for reminders; .ics for calendar
- Web-first, no native app for v0

## Canonical docs — read before any architectural change
- @decisions.md       append-only architectural decisions
- @state_machines.md  Event / RSVP / Payment / Attendance contracts
- @scenarios.md       user-facing edge-case behaviors
If a change would contradict any of these, stop and ask.

## Commands
- Run app:       .venv/bin/uvicorn app.main:app --reload
- Run skeleton:  python skeleton_02_payment.py
- Tests:         .venv/bin/pytest
- Lint/format:   .venv/bin/ruff check . / .venv/bin/ruff format .
- Dev deps:      pinned in requirements-dev.txt

## Money-handling rules (NON-NEGOTIABLE)
- All amounts in integer cents. Never float.
- Capturing less than authorized RELEASES the remainder — it is NOT a
  refund. No Refund object on the happy path.
- Removing an attendee before capture VOIDS the authorization, never
  refunds it.
- Refund = reversing an already-captured charge, only.
- Every PaymentIntent create/capture uses an idempotency key.
- Extended Authorization is deferred — capture window is 7 days from
  authorization, not 30. Bound any auto-settle by that expiry.
- A capture and its matching attendance update happen together, or
  neither does.

## Code style
- Type hints on every function signature.
- Async for anything touching the DB or Stripe.
- Comments explain WHY, not WHAT.
- Keep lines narrow — no horizontal scroll.

## How to work here
- Payment and state-machine code is load-bearing: explain the
  mechanism and let me review or write it. Do not author it wholesale.
- Never call the live Stripe API in tests — use test tokens / a mock.