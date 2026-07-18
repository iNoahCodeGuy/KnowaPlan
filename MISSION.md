# Mission: Own KnowaPlan as its developer

## Why

I review this codebase but did not author it, and on 2026-07-29 it
takes real money from my friends through my Stripe account. I want
to own it the way its developer would — the architecture and the
decisions behind it, how the code actually works, and how it
deploys — so I can add features, catch bugs in review, and explain
the system to another engineer, not vibe-code on top of it.

## Success looks like

- Explain the architecture — the layers, and the path from one tap
  to one charge — to another engineer in five minutes, unaided
- Given a diff to app/payments.py or app/settlement.py, name the
  invariant it breaks
- On 7/29, diagnose a failed charge from the roster alone
- Add a small feature end-to-end (route → service → model → test)
  without violating a state table or a money rule
- Explain every line of the Dockerfile and every env var; run the
  live flip and the day-of runbook without help
- Author the next milestone (walk-ins, refunds) rather than
  review it

## Constraints

- **12 days** to the live event (2026-07-29); feature work freezes
  ~7/19 — after that, drills and runbook practice only
- **Inverted baseline** (learning-records/0001): fluent in the
  decisions — I made every decisions.md entry under grilling —
  thin on mechanics (async, SQLAlchemy, Stripe). Teach mechanics
  anchored to decisions I already own; never re-teach decisions.
- Junior-dev explanations (CLAUDE.md): plain language, define
  terms, concrete scenarios. Short lessons; the codebase is the
  curriculum — no toy examples.

## Out of scope

- The hold model (superseded 2026-07-15) — history, not a target
- Twilio / SMS infrastructure (decided out of v0)
- Alembic migrations (deferred to live dogfood)
- Frontend beyond the /r/ Payment Element island
