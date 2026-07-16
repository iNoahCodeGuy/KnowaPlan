# Mission: The KnowaPlan money path, to production

## Why

I own a real-money app that I reviewed but did not author. On
2026-07-29 it takes real money from my friends, through my Stripe
account, at a pickleball court with nobody to escalate to. I want to
understand it well enough to take it to production myself and own it
there — to be the engineer who knows why it works and what breaks it,
not the one holding a system somebody else built.

## Success looks like

- On 7/29, a charge fails and I diagnose it from the roster alone —
  no Stripe dashboard archaeology, no asking Claude
- I can look at any Payment row and say whether money moved, in ten
  seconds, and name the next action
- I can list what still stands between here and production, and close
  each gap myself
- Given a diff to `app/payments.py` or `app/settlement.py`, I can name
  the invariant it breaks
- I can author the next milestone (walk-ins, refunds) rather than
  review it
- I can explain the money path to another engineer in five minutes

## Constraints

- **13 days** to the live event (2026-07-29). Real money, real
  friends, real trust. The deadline is the curriculum's spine.
- **Unusual baseline**: new to async, SQLAlchemy, and Stripe
  *mechanics* — but fluent in this codebase's *decisions* (I made
  every entry in decisions.md, under grilling). Teach mechanics by
  anchoring them to decisions I already own.
- Explanations pitched at a junior engineer (CLAUDE.md): plain
  language, define terms, concrete scenarios over abstractions.
- Short lessons. The codebase is the curriculum — no toy examples.

## Out of scope

- Rebuilding the hold model (superseded 2026-07-15) — read it as
  history, not a target
- Twilio / SMS infrastructure (decided out of v0)
- Alembic migrations (deferred to live dogfood, decisions.md
  2026-07-16)
- Frontend beyond the `/r/` Payment Element island
