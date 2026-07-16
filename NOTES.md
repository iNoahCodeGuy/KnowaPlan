# Teaching notes — KnowaPlan

Working scratchpad. Preferences, observations, and things to remember
when designing the next lesson.

## How Noah wants to be taught

- **Staff engineer → junior engineer.** Stated 2026-07-16. Not
  "explain it simply" — explain it the way a senior colleague walks a
  new hire through a system they'll be on call for.
- **Production is the frame.** "How this works AND how this goes into
  production." Every lesson should move the 7/29 ball, not just impart
  facts.
- Matches CLAUDE.md's existing instruction (2026-07-16): plain
  language, define terms, concrete scenarios over abstractions.
- Repo convention: narrow lines, no horizontal scroll. Lessons inherit
  the same restraint — narrow measure, short sections.

## The baseline paradox — read this before writing any lesson

Noah self-assessed as "new to most of it" (async, SQLAlchemy, Stripe)
while simultaneously being the author of every decision in
`decisions.md`, made under grilling. That is not a beginner. It's an
**inverted profile**: strong architecture, thin mechanics.

Practical consequence: never teach a mechanic cold. Anchor it to a
decision he already owns.

- ✅ "You decided record-first. Here's what a transaction actually
  *is*, which is why it works."
- ❌ "Let's learn about database transactions."

See [learning-records/0001](learning-records/0001-inverted-baseline-decisions-fluent-mechanics-thin.md).

## Lesson design conventions established

- Components live in `assets/`: `lesson.css` (Tufte-ish, print-clean,
  no web fonts — must work from `file://`), `quiz.css` + `quiz.js`
  (retrieval practice, one shot per question, feedback shown for the
  *chosen* answer so wrong answers teach).
- Quiz choices: **equal word count** across options (3 words each in
  Lesson 1), same button width, same type. No formatting tells.
- Every lesson ends with: one primary source, a "ask me things" nudge,
  and a link to the field guide + next lesson.
- Reference docs are the durable artifact — lessons get read once,
  references get printed. Build the reference alongside the lesson.

## ⚠️ MID-STEP CHECKPOINT — read this first (2026-07-16)

A step is **open and unfinished**. Suite is green by construction: no
code was written, no test was added, nothing is stubbed. But a decision
was made and its implementation is pending.

**Decision made by the owner (2026-07-16):** on the Stripe-fee fork,
he chose **"attendees cover it"** — gross up the charge so the planner
nets their exact share. This *overrode* my recommendation (which was:
change no code before 7/29, just record the absorption). His call; it's
the only option that moves his bottom line.

**Nothing has been implemented. Six shaping calls are UNANSWERED:**

1. Where does the fee rate live? → *Recommended:* `app/config.py`
   settings (`STRIPE_PCT_BPS=290`, `STRIPE_FIXED_CENTS=30`), not a
   module constant — a rate change becomes a deploy, not a code edit.
2. Foreign cards under-collect (international is +1.5%, so a $30 share
   under-collects ~45¢). Who eats it? → *Recommended:* the planner,
   silently, but **recorded** — an unrecorded absorption is the exact
   bug being closed.
3. Does the RSVP estimate gross up too? → *Recommended:* **yes,
   load-bearing.** Estimate at $30 + card hit at $31.20 rebuilds the
   surprise `scenarios.md` exists to prevent. Touches
   `estimated_share_cents` at creation + the snapshot-freeze rule
   (decisions.md 2026-07-16), so arguably its own step.
4. Rounding direction? → *Recommended:* `ceil`, never under-collect.
5. What does `SettlementReport.share_cents` mean now? → *Recommended:*
   report both `share_cents` (recouped) and `charge_cents` (billed);
   the gap is the fee and the planner should see it.
6. Cap-and-absorb comparison? → *Recommended:* grossed-to-grossed, or
   `min()` compares different units and the cap fires spuriously.

**KNOWN BUG in my own draft — do not ship it as written:**

```python
def gross_up(share_cents: int) -> int:
    numerator = (share_cents + FIXED) * 10_000
    denominator = 10_000 - PCT_BPS
    return -(-numerator // denominator)   # ceil, integers only
```
Verified against the real ledger (Stripe rounds the pct: $32 → $1.23,
i.e. 92.8 → 93):
- share $30.00 → gross_up $31.21 → fee $1.21 → nets **$30.00** ✓
- share $40.00 → gross_up $41.47 → fee $1.50 → nets **$39.97** ✗ (−3¢)

The formula does not invert Stripe's rounding exactly. **Write the
property test first** (`charge − fee(charge) == share` across
$1–$500); it will fail and pin the real formula.

**Owner still owes:** confirm/overrule the six calls, and say whether
he writes `gross_up` against my failing tests, or reviews a full draft
line by line (CLAUDE.md: money code is not authored wholesale).

## Open threads / candidate next lessons

1. **Lesson 2 (queued): "Why the stamp and the state can't be one
   write."** What a transaction/commit is; why Stripe can't be in it;
   why record-first is the only honest option. Row 2 of Lesson 1 is the
   hook. Needs the SQLAlchemy resource gap closed first.
2. **The production gap lesson.** What actually stands between here and
   7/29 — the `card_payments` capability blocker is the headline. This
   may need to jump the queue; it's a real blocker, not a concept.
3. Reading `settle_event` end to end — the loop, the per-attendee
   failure containment, the planner-skip.
4. The capability-URL model as *the* auth story (and its accepted risk).
5. Where the money actually lands: Connect, `on_behalf_of`, fees.

## Glossary

Not started — deliberately. The rule is a term gets added once Noah
*uses it correctly*, not once it's been mentioned. Candidates queued
from Lesson 1: dangling charge, record-first, off-session, idempotency
key, PaymentIntent.

## Findings parked for the owner (not teaching material — real work)

Surfaced in-session 2026-07-16; **not yet actioned**, because CLAUDE.md
requires alignment before doc changes. Do not let these rot.

### THE BIG ONE — planner absorbs Stripe fees, unrecorded

Verified against the real account, three ways (empirical ledger + API
params + primary docs). `transfer_data` omits `amount` and there's no
`application_fee_amount`, so the **full** share transfers to the
connected account and the **platform** is debited 2.9% + 30¢. The
platform is Noah. Real balance on 2026-07-16: **−$2.69** from three
test charges.

Consequence: on a $120 court / 4 players / $30 share, friends pay
$30.00 and **the planner pays $33.51**. `scenarios.md` states "Nobody
is ever charged a cent more than anyone else" and bounds planner
absorption at "headcount − 1 cents" (3¢). Reality is 351¢. **The doc
is currently false.**

- The lever is `application_fee_amount` or `transfer_data.amount`.
- `controller.fees.payer` is **NOT** the lever (direct charges only).
- Account type is **NOT** the lever (fee follows charge type).
- Design fork put to the owner 2026-07-16; recommendation was
  **change no code before 7/29** — fix the false doc, run the event,
  revisit after. Awaiting decision.
- Taught in [lessons/0002](lessons/0002-where-the-money-actually-goes.html).

### Doc/reality divergences

1. `success_url` — the recorded reason (account-shaped) is wrong; it's
   `ui_mode`-conditioned. The fix is right, the lesson recorded is false.
2. Idempotency drift — entry says "raises IdempotencyError forever";
   truth is worse (silently charges anew after ~24h pruning).
3. 255-char columns — right call, but "Stripe publishes no length
   guarantee" is an argument from absence; Stripe *documents* 255 and
   recommends `VARCHAR(255)`.
4. ~~`card_payments` capability — 7/29 blocker~~ **RESOLVED, not a
   blocker.** Checked the account: `card_payments: active`,
   `charges_enabled: true`, `currently_due: []`.
5. "Never re-fire a saved card" is self-imposed, not a Stripe limit.
6. **CLAUDE.md + decisions.md say "Connect (Standard)". It isn't.**
   The account is Express-equivalent (`type: "none"`, controller
   properties matching Stripe's documented Express response). It is
   correctly configured and nothing is broken — but the docs name the
   wrong thing, and *that* is what sent me down a wrong path (below).

### My own error, recorded because it's the instructive one

I told Noah `controller.fees.payer: "application"` was "the culprit"
for the fee and implied Standard would fix it. **False.** Destination
charges bill the platform "regardless of the entity responsible for fee
collection." Same failure mode as the `success_url` entry: a plausible
cause sitting adjacent to the symptom, which survives review precisely
because it's plausible. Worth keeping as a teaching artifact — it's in
Lesson 2 as Q3, and Noah watching me get it wrong and get corrected by
a primary source is better pedagogy than me being right would have been.
