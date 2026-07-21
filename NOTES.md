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

**CORRECTED 2026-07-18 — the earlier "known bug" note was itself
wrong (re-verified across every share value $1–$500):**

```python
def gross_up(share_cents: int) -> int:
    numerator = (share_cents + FIXED) * 10_000
    denominator = 10_000 - PCT_BPS
    return -(-numerator // denominator)   # ceil, integers only
```
This draft NEVER under-collects. It OVER-collects +1¢ on ~51% of
share values $1–$500:
- share $30.00 → bills $31.21 → fee $1.21 → nets **$30.00** ✓ exact
- share $40.00 → bills $41.51 → fee $1.50 → nets **$40.01** ✗ (+1¢)
  (the old note's $41.47 / −3¢ figures were miscomputed)

The honest formula is a search, not a ceil-inversion: the SMALLEST
charge c with c − fee(c) ≥ share, where fee(c) =
round-half-up(2.9% × c) + 30¢. That nets EXACTLY the share on every
value $1–$500. The property test pins both halves — make-whole AND
minimal. Flagged gap: Stripe's rounding mode at exact half-cents is
unverified; the empirical ledger never hit one.

**Owner still owes:** confirm/overrule the six calls, and say whether
he writes `gross_up` against my failing tests, or reviews a full draft
line by line (CLAUDE.md: money code is not authored wholesale).

## Session log — 2026-07-17 (mission widened; Lesson 3 + the map)

- Noah deleted MISSION.md and re-invoked /teach: "what do I need to
  know about this codebase" — architecture, decisions, how the code
  works, deployment, feature work, explainability; "not just vibe
  code." MISSION.md rewritten around whole-codebase ownership (old
  text preserved in git, commit a472e7a); learning-records/0003
  records the widening. 7/29 remains the spine; ~7/19 freeze noted.
- Shipped **Lesson 3, "The shape of the codebase"** + the
  **codebase map** (reference/codebase-map.html) — the map is now
  the curriculum's table of contents, with territory statuses, and
  the direct answer to "what do I need to know."
- Verified before teaching, not assumed: web.py assigns zero state
  columns (grepped), payments.py never commits (read), settlement.py
  imports stripe only for exception types. FastAPI router +
  dependencies-with-yield and SQLAlchemy asyncio pages fetched and
  quoted — the stack gap in RESOURCES.md is closed.
- Lesson 3 completion is UNVERIFIED — no quiz answers observed yet.
  Confirm the placement rules landed before building the
  transactions lesson on top of them.
- **Review quiz (lessons/0004) result: 6/7, sole miss Q6.** Both
  money-losing diagnosis traps (Q3 dangling, Q5 pi_-not-receipt)
  correct — Lesson 1 skill is durable. Q6 (which line of code sends
  the full transfer = `transfer_data` w/ no `amount`) was the miss,
  with Q2/Q4 correct: concept solid, concept→code mapping thin. See
  learning-records/0004.
- **Lesson 3 quiz: 2/4** — missed Q3 (who commits after
  charge_share → settlement.py) and Q4 (internal-host links → the
  Dockerfile proxy flags); got Q1/Q2 (transition-table / state
  ownership). THIRD consistent data point: every miss he's made
  (review Q6, L3 Q3, L3 Q4) is the concept→code seam. Design layer
  perfect; substrate-mapping thin. See learning-records/0005. Named
  the pattern to him explicitly.
- **BUILT Lesson 4** (lessons/0005-follow-one-charge-through-the-
  code.html): line-by-line trace of one $30 — COMMIT #1 stamp →
  charge_share (no session param = can't commit; transfer_data no
  amount) → _collect COMMIT #2. Knockout for Q3 = the signature has
  no session. Closes Q3 + Q6, re-grounds Lesson 1's crash map.
  UNVERIFIED (no quiz result yet). Quiz wiring browser-tested OK.
- **Still open / queued:** (a) L3 Q4 deployment lesson — proxy
  flags, request.base_url, the no-BASE_URL decision — its own
  territory, NOT in Lesson 4. (b) async lesson (await on the Stripe
  call + roster poll). (c) reassess whether the standalone
  transactions-concept lesson is still needed or now folds into
  async, since Lesson 4 gave the commit boundary concretely.

## Session log — 2026-07-18 (lineages merged; checkpoint corrected)

- Found a fork: the 2026-07-17 local session above was never
  committed or pushed, so the web session — unaware of it — built
  the record-first concept lesson as a second "Lesson 3" (commit
  74dda83 on claude/knowaplan-teach-continue-sydfoq). Owner chose:
  keep both. The web lesson is now lessons/0006, retitled Lesson 5;
  the whole lineage lives on that branch, committed and pushed.
  The two overlap by design, not by accident: local Lesson 4 is the
  code-level trace, web Lesson 5 the transaction concept under it.
- Corrected the checkpoint's gross_up claim (see above): the draft
  over-collects +1¢ on ~51% of values, never under; honest formula
  = smallest make-whole charge. Owner confirmed recording.
- Lesson 5 (0006) quiz: unverified — ask for the score.
- LIVE connected account confirmed: acct_1TuKMK1a8RMP4gcA,
  card_payments + payouts active. Supersedes earlier notes'
  references to the test-mode account check.
- Owner un-parked gross_up (chose it over the settle_event lesson
  and the production checklist; feature freeze ~7/19). Next queued
  lesson remains settle_event end-to-end.

## Session log — 2026-07-18 (cont.): Lesson 6 + a quiz-integrity bug

- **Shipped Lesson 6** (lessons/0007-settle-event-end-to-end.html):
  the four phases, `charged` vs `participants` as the one-line
  planner skip, the try INSIDE the loop, the decline-is-not-an-
  exception subtlety, resume semantics via the `existing` dict, and
  the dangling/unpaid label line. Ends by placing his pending
  gross_up wiring (net `share` vs billed stamp, the units trap in
  the cap) — the lesson doubles as the scaffold for the code he
  owes. Verified before teaching: `issubclass(CardError,
  StripeError)` is True and RuntimeError is not a StripeError
  (checked in the venv, not recalled), and all four cited tests run
  green under the names quoted.
- **Found a real defect in the quiz component's usage.** Three
  lessons had unequal-word-count options, violating the workspace
  convention (a length difference is a formatting tell, so a right
  answer stops proving recall). Worst case was Lesson 6's own draft
  Q2, where the CORRECT answer was the short one — caught and fixed
  before shipping.
  - lessons/0005 Q1 (the knockout for his L3 Q3 gap) had a 4-word
    distractor among 3s. Fixed BEFORE he takes it — that quiz is
    still unverified, so the data would have been muddy.
  - Review Q6 (lessons/0004) — the miss the whole recent curriculum
    was built on — had the correct answer as the only option not
    starting with "The". Normalized. **The inference in
    learning-records/0004 still holds and is arguably stronger:**
    the tell pointed AT the right answer and he still missed it, so
    the concept→code reading is not an artifact of option shape.
- **New durable component: assets/check_quiz.py** — an authoring
  guard (not shipped in lessons) that validates data-answer/
  data-key/feedback wiring and equal word counts. Run it on every
  lesson before shipping; all 7 pass now.
- Still unverified: quiz results for Lessons 4, 5, and 6. Ask.

### ⚠️ POSITION BIAS — he caught it, and it voids the Lesson 6 score

Noah scored 1/5 on Lesson 6 and asked "is there a reason why it's
always A?" Measured it: **82% of all 33 questions had the answer in
slot 1; lessons 3–6 were 100%** (21 straight). That is a broken
instrument, and worse than an easy one — a learner who spots the run
starts AVOIDING slot 1, which is exactly his transcript (wrong picks
at slots 4/4/4/3, the single right one at slot 1).

- **Treat the 1/5 as void.** Full reasoning in
  learning-records/0006. settle_event comprehension is UNMEASURED,
  not failed; do not branch the curriculum on it.
- Earlier scores (6/7 review, 2/4 L3) carried the same bias but are
  inconsistent with blind slot-picking, so the concept→code seam
  finding in records 0004/0005 still stands.
- **Fixed:** all lessons rebalanced to 30/24/24/21 across slots, and
  check_quiz.py now FAILS any lesson where one slot holds the answer
  >50% of the time. Run it before shipping any lesson — it has now
  caught two distinct real defects (word-count tells, position bias).
- Lesson: he is a sharper reviewer of my instruments than I was.
  When he questions a lesson's construction, measure it before
  answering — both times the measurement was worse than my guess.

## Session log — 2026-07-21 (Lesson 7: the three accounts)

- **Shipped Lesson 7** (lessons/0009-the-third-account.html) + a durable
  field guide (reference/three-accounts.html). The topology
  learning-records/0007 promoted to next: cardholder / platform /
  connected, what a refund touches vs what a transfer reversal touches,
  the sunk fee. Built on HIS OWN two live 7/21 charges ($1.00 saved card,
  $1.66 link) and their real transfer ids (tr_3TvdcV…, tr_3Tve3B…, both
  reversed: false), not Connect theory — exactly as 0007 asked.
- **Inverted the format** per learning-records/0008: the lesson opens on
  his broken 7/21 ledger with a "stop — what's wrong?" prompt before any
  explanation, then teaches the mechanism. First time a lesson leads with
  a scenario instead of the concept.
- **The pedagogical spine** is the solo-nets-to-zero trap: solo, platform
  −$1.33 + connected +$1.00 combine to the same −$0.33 as the reversed
  case, so the reversal changes nothing he can see — which is *why* he
  skipped it and reported complete in good faith (0007's strongest
  signal, reflected back at him). The lethal case (a second planner) is
  the $30 worked example.
- **Verified before teaching** (the NOTES pattern; Stripe facts have
  bitten this curriculum before): both load-bearing claims quoted from
  Stripe's own text — refund on a destination charge does NOT reverse the
  transfer ("the destination account retains the funds by default… set
  the reverse_transfer parameter to true"), and Stripe keeps the fee on a
  refund ("fees from the original charge are not returned"). Sources added
  to RESOURCES.md.
- **Closing action fixes his real books:** reverse the two live transfers,
  read reversed: true. Offered to walk the exact dashboard clicks (did
  NOT assert button labels I couldn't verify — docs.stripe.com is
  egress-blocked this session; see RESOURCES note).
- check_quiz.py: CONTRACT OK — words equal within each question, answer
  slots [2,3,1,4] (no bias). **Quiz UNVERIFIED — ask for the score.** No
  learning record written: nothing was demonstrated yet, only built
  (LEARNING-RECORD-FORMAT: coverage ≠ learning).
- Map updated: the → three-accounts row flipped to ✓ Lesson 7; the "two
  transfers awaiting reversal" open item now points at the lesson's
  action and clears when he reverses both.

## Open threads / candidate next lessons

> The **codebase map's "Next lessons" table is the live queue** now
> (reference/codebase-map.html) — it tracks ✓/→/· status. The list below
> predates Lessons 4–7 and is kept only for the notes it carries;
> trust the map for what's shipped.


1. **Transactions & record-first mechanics** — what a commit
   guarantees, why Stripe can't be inside one, the two-commit
   choreography. SQLAlchemy source verified; still want a
   commit-semantics primary source (RESOURCES gaps). NEXT in queue.
2. async/await — anchored to charge_share and the roster poll.
3. Reading `settle_event` end to end — the loop, per-attendee
   failure containment, the planner-skip.
4. The capability-URL model as *the* auth story (and its accepted risk).
5. Deployment & live-flip drill — runbook rehearsal before 7/29.
6. ~~Where the money actually lands~~ → became Lesson 2.
7. ~~Production gap / `card_payments` blocker~~ → resolved, not a
   blocker (findings below); folded into the map's open-items table.

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
   `charges_enabled: true`, `currently_due: []`. *(That check was
   the test-mode account; re-confirmed 2026-07-18 on the LIVE
   account `acct_1TuKMK1a8RMP4gcA` — card_payments + payouts
   active.)*
   **⚠ 2026-07-21 — that check was insufficient, and it cost the
   first live test.** Every charge failed
   `insufficient_capabilities_for_transfer` while all of the fields
   above still read healthy, *including* `transfers: active`. On a v2
   account the v1 `capabilities` object is a projection; the governing
   fact was `applied_configurations: ["merchant"]` — the dashboard
   wizard had never granted the **recipient** configuration, so the
   account could be merchant of record (`on_behalf_of` worked) but
   could not RECEIVE a transfer (`transfer_data.destination` did not).
   Fixed by requesting
   `configuration.recipient.capabilities.stripe_balance.stripe_transfers`
   via `POST /v2/core/accounts/{id}` with
   `Stripe-Version: 2025-08-27.preview`; verified by re-running the
   exact failing PaymentIntent call. **Any future connected account
   needs BOTH configurations.** Same failure mode as items below: a
   plausible status field adjacent to the symptom. The reliable
   diagnostic was isolating the parameters — `on_behalf_of` alone
   succeeded, `transfer_data` alone failed — and reading Stripe's own
   error text rather than an account summary.
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
