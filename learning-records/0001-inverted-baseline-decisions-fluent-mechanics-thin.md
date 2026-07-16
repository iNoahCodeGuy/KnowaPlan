# Inverted baseline: fluent in the decisions, thin on the mechanics

Noah self-assessed as "new to most of it" — async, SQLAlchemy, and
Stripe mechanics are largely opaque; he would struggle to write
`app/payments.py` from scratch. But he is simultaneously the author of
every entry in `decisions.md`, each made under adversarial grilling,
including the 2026-07-15 charge-at-close pivot and the record-first
mechanism. He can defend *why* the system is shaped this way and cannot
yet say *what `await` does*.

This is not a beginner profile and must not be taught as one. It is
inverted from the normal case: architecture strong, substrate thin.
Most learners have the mechanics and lack the judgement; here it's the
reverse.

**Implications for every future lesson:**

- Anchor each mechanic to a decision he already owns. "You decided
  record-first — here's what a transaction *is*, which is why it works"
  lands; "let's learn about transactions" wastes the asset.
- Do not re-teach the decisions. He'll be bored, and worse, he'll
  correctly suspect I haven't read his docs.
- The gap to attack is the one between "I chose this" and "I could have
  found the bug in it." He reviews load-bearing money code (CLAUDE.md)
  but currently reviews it at the *design* layer only.
- Expect fast uptake on anything with a decision to hang it on, and
  genuine slowness on free-floating mechanics (async, ORM sessions).
  Budget lesson time accordingly.

**Evidence:** the `/teach` intake (2026-07-16). Also corroborated by
CLAUDE.md's own standing instruction — "explanations are written for a
junior developer" (2026-07-16) — recorded by Noah about himself, and by
"payment code: explain the mechanism and let me review or write it. Do
not author it wholesale."

**Mission:** he selected *all four* framings (run 7/29 solo, review
money code for real, build the next milestone, learn the stack) and
reframed as "how this works and how this goes into production." Resolved
into a single spine in [[MISSION.md]] — production on 2026-07-29 is the
forcing function; the other three are served by getting there.
