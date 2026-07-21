## 2026-05-26: Extended Authorization requires platform approval
**Finding:** request_extended_authorization="if_available" raises
InvalidRequestError in test mode — Stripe requires explicit platform
approval for flexible payment features, even with the if_available flag.
**Impact:** RSVPs cannot be accepted more than 7 days before an event
until Stripe approves the platform. Not blocking for v0 dogfood phase
(friend group, known schedule). Must be resolved before opening to
strangers.
**Action:** Contact Stripe support to request flexible payments eligibility
before end of Phase 1.
**Replaces:** Prior assumption in decisions.md that Extended Authorization
was available from day one.

## 2026-05-28: Capture-less is a release, not a refund; add `voided`
**Alternatives:** (a) Keep `partially_refunded`, refund the uncaptured
overage. (b) Model partial capture as its own state.
**Chose:** Remove `partially_refunded`. Capturing less than the authorized
worst-case releases the uncaptured remainder automatically (Stripe reverses
it on the card network) — no Refund object is created. Add an explicit
`voided` Payment state for authorizations released without any capture
(no-show, attendee removed pre-capture, event cancelled pre-capture, auth
expiry). `refunded` is now reversal of an already-captured charge only.
**Why:** `partially_refunded` contradicted the manual-capture flow in
skeleton_02 and the capture-at-actual decision (2026-05-22); it would have
generated refund code that never runs on the happy path. `voided` was
missing entirely, so no-shows and cancellations had no terminal state.
**Replaces:** The `partially_refunded → refunded` chain in state_machines.md
and the "refund their share" language in the transfer scenario — both
corrected to void.
**Hook, not prose:** A capture/refund guard belongs in a hook — block any
path that issues a Refund against an uncaptured authorization, and require
capture-less paths to capture (amount < hold) or cancel, never refund. This
is a money invariant; it must fire 100%, not 70%.

## 2026-05-28: Auto-settle backstop bounded by authorization expiry
**Alternatives:** (a) Fixed +6-day-post-event backstop. (b) Backstop at the
planner's chosen settle target with no expiry bound.
**Chose:** Effective backstop = min(planner's configured settle target,
earliest authorization expiry across attendees). Reminders re-anchor to the
effective backstop.
**Why:** Extended Authorization is deferred (2026-05-26), so the capture
window is 7 days from authorization, not from the event. An event with early
RSVPs can have holds that expire shortly after the event — a fixed
+6-day-post-event backstop would fire after the hold is gone, the capture
fails, and the planner silently eats the cost. Bounding by expiry prevents
lost captures.
**Locks in:** Settlement scheduler computes the backstop per-event from the
earliest attendee auth expiry, not a fixed offset; reminder timing derives
from it.
**Hook, not prose:** Scheduler guard belongs in a hook — refuse to schedule
or fire an auto-settle capture after any attendee's auth expiry. Money
invariant.

## 2026-07-08: Re-record of lost decision (2026-05-22): capture at actual share
**RECONSTRUCTED** — the original entry predates git history and was lost;
re-recorded from skeleton_02 and the entries that cite it. Owner may
correct the wording; the date in the title preserves the original
ordering of decisions.
**Alternatives:** (a) Charge the worst-case share upfront at RSVP and
refund the overage after the event. (b) No hold at all — invoice
attendees their share after the event.
**Chose:** Authorize the worst-case share at RSVP (manual-capture hold),
capture only the actual share once attendance is known.
**Why:** (a) makes a refund the happy path and shows attendees a real
charge before the event; (b) leaves the planner fronting the whole cost
and chasing payments afterward. The hold guarantees funds without moving
money until the true per-person cost exists.
**Locks in:** PaymentIntents with capture_method="manual"; capture ≤
authorization; the release/void/refund semantics later formalized on
2026-05-28.

## 2026-07-08: RSVP declined → going while the event is open
**Conflict resolved:** scenarios.md ("Maybe doesn't convert by deadline")
lets an auto-declined attendee tap Going again until the event closes,
but the RSVP machine defined no declined → going transition.
**Chose:** scenarios.md wins — add declined → going, valid only while the
Event is open (a service-level guard; the transition table itself has no
event context). Converting requires a fresh card authorization, same as
any RSVP. Once the event is closed, the late-RSVP approval and walk-in
paths in scenarios.md apply instead.
**Why:** a friend who mis-tapped or auto-declined and changed their mind
is a common case in a known group; forcing planner intervention adds
friction with no money-safety benefit — the fresh authorization is the
safety.
**Locks in:** app/state_machines.py RSVP table and the test transition
matrix carry the pair; declined is no longer a terminal RSVP state.

## 2026-07-08: Payment attempt grain and idempotency keys
**Alternatives:** (a) One Payment row per attendee per event, reused
across re-authorizations. (b) Partial unique index over active states
only.
**Chose:** Payment rows are unique on (event_id, attendee_id, attempt).
A re-authorization after a terminal state (voided, abandoned) is a NEW
row with the next attempt number; terminal rows remain as audit records.
Stripe idempotency keys derive from (payment.id, operation).
**Why:** Stripe replays a reused idempotency key's original response for
~24h. With keys derived from (event, attendee, operation), voiding an
attendee and re-adding them the same day would replay the already-
cancelled PaymentIntent — no error raised, no hold placed, planner
silently unprotected. A new row per attempt yields a fresh key by
construction, while retrying the SAME operation after a network blip
still reuses its key and therefore cannot double-charge.
**Locks in:** Payment uniqueness in app/models.py; the key-derivation
rule documented in app/payments.py; terminal Payment rows are never
reused for new money movement.

## 2026-07-13: Next milestone is a test-mode demo; live dogfood after
**Alternatives:** (a) Build straight toward a live event with real
cards. (b) Test-mode demo first: the full vertical slice run with
Stripe test tokens, planner and attendees all played by the owner.
**Chose:** (b). The demo delivers: create event → share link → RSVP +
authorize (test cards) → close at start time → mark attendance →
capture/void → settled. Deferred from the slice: the auto-settle
backstop scheduler (settlement is manual, but auth_expires_at is still
recorded and captures past expiry are refused — the invariant holds
without the timer), real Twilio (SMS bodies are logged), .ics,
walk-ins, transfer-organizer, and the failed → resolved settle-up flow
(planner chases manually).
**Why:** every correctness lesson — transitions, idempotency,
capture-below-auth — is learnable in test mode where a bug costs
nothing; at a live event it costs real money and the group's trust.
Everything deferred is either a convenience or has a manual fallback;
nothing deferred is load-bearing for the money path.
**Locks in:** live dogfood is its own follow-up milestone: live keys,
activated Connect account, hardened attendee-facing copy, one real
event.

## 2026-07-13: Identity via capability URLs; no accounts in v0
**Alternatives:** (a) SMS-OTP login. (b) Accounts with passwords.
(c) Capability URLs — unguessable tokens as the only credential.
**Chose:** (c). Three tokens, one per purpose, never reused across
purposes: an event link /e/{token} the planner texts the group (view
event, start an RSVP by entering name + phone — no phone verification);
a per-attendee link /r/{token} minted at RSVP (lets that attendee
change their own RSVP — this is how maybe → going and declined → going
work without sessions); a planner admin link /admin/{token} minted at
event creation (attendance, settlement, cancellation). Tokens are
~128-bit random, stored in the DB.
**Why:** (a) drags Twilio into the demo milestone and adds friction at
the court; (b) is not v0. The card authorization is the real gate; in
a known friend group a mistyped phone is a nuisance, not an attack.
**Accepted risk:** whoever holds the admin link IS the planner. Fine
for the friend-group v0; real login + OTP is a later milestone, before
opening to strangers.

## 2026-07-13: Worst-case share derived from a minimum headcount
**Alternatives:** (a) Planner types a worst-case dollar figure
directly. (b) Planner enters total cost and a minimum headcount; the
app computes worst_case_share_cents = ceil(total / min_headcount).
(c) Recompute the worst case dynamically as RSVPs arrive.
**Chose:** (b). A $120 court with "at least 4 of us" holds $30 per
attendee; the RSVP page says the likely charge is less.
**Why:** min headcount makes the planner's bet explicit — if only 3
show, the actual share ($40) exceeds the hold ($30), capture is capped
at the authorization, and the planner knowingly eats the gap (the same
rule scenarios.md already sets for cost increases). A raw dollar input
hides that bet. (c) would force re-authorizations mid-flight.
**Locks in:** ceil, never floor, for the hold (never under-authorize);
min_headcount stored on Event; the shortfall is computed and shown to
the planner at settlement, never silently absorbed.

## 2026-07-13: Uneven splits — everyone pays floor, planner absorbs
**Alternatives:** (a) Assign the leftover cents to a few attendees so
the totals match exactly. (b) Everyone pays floor(total / headcount);
the planner absorbs the remainder.
**Chose:** (b). Max planner loss is headcount − 1 cents per event.
**Why:** distributing cents is "fairer" by pennies but generates "why
did I pay more than him?" — social cost with no monetary upside at
this scale.

## 2026-07-13: auth_failed — terminal Payment state for RSVP declines
**Problem:** the machines modeled capture failure (authorized →
failed) but not a decline at authorization time. The idempotency key
derives from payment.id, so the Payment row exists before the Stripe
call — a declined auth left a row stuck in `none` with no terminal
state.
**Alternatives:** (a) Reuse `failed`. (b) Add terminal `auth_failed`
(none → auth_failed).
**Chose:** (b). The RSVP stays `going` (= said yes, not yet covered),
the roster shows them unpaid, and a retry with another card is a NEW
attempt row — fresh idempotency key by construction (2026-07-08).
**Why:** `failed` means a CAPTURE failure and drags the settle-up
grace flow (resolved/abandoned) with it; an RSVP-time decline has no
hold, no grace period, and no money at risk — a different animal that
deserves its own state.

## 2026-07-13: Record-first money movement
**Problem:** "a capture and its matching attendance update happen
together, or neither does" cannot be literal — Stripe is not part of
the DB transaction, and a crash between the two calls is possible.
**Alternatives:** (a) Stripe first, then one transaction writing both.
(b) Record-first: one transaction writes the attendance change AND a
request stamp (capture_requested_at / void_requested_at) on the
Payment row; then the Stripe call; then a second write sets the final
state (captured / voided).
**Chose:** (b), symmetrically for captures and voids.
**Why:** (a)'s crash leaves money moved with no DB trace — discovered
by an angry text, reconciled by digging through the Stripe dashboard.
(b)'s crash leaves a dangling row findable by query (stamp set, state
still authorized); the admin page surfaces it, and the retry reuses
the SAME idempotency key, so Stripe replays the original outcome and
the books converge whether or not the first call landed. A missed
void matters too: the hold sits on a friend's card until expiry and
reads as "they charged me anyway."
**Principle:** the database must always know at least as much as
Stripe. Write intent before moving money; discrepancies become
queryable, not anecdotal.
**Locks in:** capture_requested_at and void_requested_at columns on
Payment; the "together or neither" rule in CLAUDE.md now names this
mechanism.

## 2026-07-13: No Stripe webhooks until live dogfood
**Alternatives:** (a) Stand up a webhook endpoint in the demo
milestone. (b) Rely on synchronous API responses plus our own
auth_expires_at guard.
**Chose:** (b). Every v0 money call — authorize (confirm=True),
capture, cancel — returns its outcome in the same request, and 3DS is
deferred (state_machines.md), so nothing arrives asynchronously.
Expiry is a deadline we already know at authorization time and enforce
locally; we don't need Stripe to phone us about it.
**Revisit at live dogfood:** disputes, bank-initiated reversals, and
eventually 3DS (authorization becomes asynchronous) all arrive only by
webhook.

## 2026-07-15: Pivot from card holds to charge-at-close
**Supersedes the hold / manual-capture money model** built across
2026-05-22 (capture at actual share), 2026-05-26 (Extended
Authorization), 2026-05-28 (release-not-refund + `voided`; auto-settle
bounded by auth expiry), 2026-07-08 (capture-at-worst-case; attempt
grain), and 2026-07-13 (record-first; `auth_failed`; worst-case from
min headcount). Those entries stay as history; this one is now the
money model. Where they conflict, this entry wins.
**Problem:** the hold model authorizes a worst-case hold at RSVP and
captures the actual share at settlement. It guarantees funds, but it
carries the system's heaviest complexity — the 7-day auth-expiry fuse,
the void path, the capture-≤-hold ceiling, the release-vs-refund
distinction, record-first crash choreography, and the money_guard
hook — plus the "you charged me already?!" pending-hold UX. For a
known friend group splitting ~$30 (the v0 scope), that complexity
insures against a risk v0 does not run: strangers and large amounts.
**Chose:** charge-at-close. No authorization, no hold at RSVP.
- Card is OPTIONAL at RSVP (a `going` or `maybe` attendee may add one
  or not; a saved card is a SetupIntent, not a hold — no money moves).
- At close the split locks: floor(total ÷ attendees marked present).
- Card on file → charged automatically for their share at close.
- No card → planner sends a tap-to-pay link; tapping shows a
  "$X to [Planner] — Pay" confirm screen before the charge.
**Sub-decisions:**
- **Close is manual, never at start time.** The Event no longer
  auto-closes when the game starts. The planner closes RSVPs; RSVPs
  and new joins stay OPEN through the game (late arrivals and brought
  friends lower everyone's share). The only automatic close is the
  settlement backstop — the planner begins marking attendance, or the
  settle timer fires.
- **Goal attendance replaces worst-case / min headcount.** The planner
  sets a goal; total ÷ goal is the ESTIMATE shown at RSVP. It sizes no
  hold (there is none) — display + expectation only.
- **Actual > estimate (fewer than goal show up):** the planner's
  choice at settlement — charge the true (higher) share, or cap at the
  quoted estimate and absorb the gap. DEFAULT, including auto-settle
  with no planner present: charge the actual share. Absorbing is an
  active generosity choice; silence must never trigger it.
- **Cardless who never pays:** one automatic nudge at +24h prompts the
  PLANNER to send a reminder; after that the balance sits on the
  roster and the planner nudges on demand. No dunning engine in v0.
- **Reminders come from the planner's own number, not Twilio.** A
  server cannot send SMS from a personal line, so the app opens the
  planner's native Messages pre-filled (recipient + amount + link) and
  the planner taps send. Zero Twilio, zero A2P registration in v0.
  (Overrides the Twilio-as-reminder-channel line in CLAUDE.md.)
- **Planner sees who owes, per event** — the roster shows paid /
  auto-pay / will-be-billed so exposure is visible before booking.
**Accepted risk — this is the guarantee we gave up:** payment is NO
LONGER guaranteed. A saved card can decline off-session at close, and
a cardless attendee can ghost the link. The planner can be stiffed —
exactly what the hold prevented. Acceptable only because v0 is a known
friend group and the amounts are small.
**Revisit trigger:** reintroduce holds the day KnowaPlan opens to
strangers OR charges amounts large enough that one decline hurts. The
hold's complexity earns its keep there; at friend-group / small-dollar
scale it does not.
**Obsoletes:** Extended Authorization (2026-05-26) and the
expiry-bounded backstop (2026-05-28) — no authorization to expire;
`auth_failed`, `authorized`, `voided`, capture-≤-hold, and the
release-vs-refund invariant — no hold to release or void. Refund stays
reversal-of-a-collected-charge only.
**Follow-up (NOT done here):** app/payments.py, app/state_machines.py,
app/models.py, the money_guard hook, and the test suite still encode
the hold model and must be reconciled under owner review (CLAUDE.md:
money + state-machine code is author-with-review). This entry and the
canonical docs move first; the code follows deliberately.

## 2026-07-16: Charge-at-close mechanism refinements
**Context:** implementing the app/payments.py bodies surfaced four
mechanism gaps the 2026-07-15 pivot left open. Settled here, before
the code; each one is a money invariant.
**1. charge_share fires from `none` only.** A saved card is charged
once per Payment row. After a decline (`unpaid`) the tap-to-pay link
is the ONLY recovery — never a saved-card re-fire, which would need
a second idempotency key and so contradict the (payment.id,
operation) rule; within Stripe's ~24h replay window it would
silently return the original decline anyway. The fixed
"{payment.id}:charge" key stays coherent: a dangling retry replays
the original outcome.
**2. One payable link per Payment row.** A Checkout Session stays
payable ~24h and poll_link_status watches only the STORED session
id, so re-minting would leave the old link live-but-unwatched — an
attendee could pay a link the DB no longer knows (double collection;
roster wrongly unpaid). create_payment_link retires the old session
first: retrieve it; if already paid, REFUSE to mint (poll and
reconcile — money already moved); if still open, expire it; then
create the new one.
**3. A declined PaymentIntent is recorded.** An off-session decline
still creates a PI at Stripe, and the DB must know at least as much
as Stripe (2026-07-13). stripe_payment_intent_id now means "latest
charge attempt" — set from the error payload on a decline,
overwritten by the collecting PI when the link pays. Payment
`state`, never this column, gates refunds.
**4. The record-first stamp includes the amount.** Stripe replays an
idempotency key only for IDENTICAL params; a dangling retry with a
recomputed (drifted) amount raises IdempotencyError forever while
Stripe may hold collected money the DB never learns about. New
column charge_requested_cents, stamped in the same txn as
charge_requested_at; charge_share refuses when the passed amount
differs from the stamp. Intent = when AND how much.
**Locks in:** the guards in app/payments.py; the
charge_requested_cents column; the state_machines.md clarification
of the "retried" sentence.

## 2026-07-16: Settlement mechanics — planner's share, the estimate, scope
**Context:** building the settlement service (the record-first
caller app/payments.py assumes) forced three decisions the
charge-at-close pivot left open.
**1. The planner is a divisor, never a charge.** A playing planner
RSVPs like anyone — an ordinary Attendee + Rsvp row, linked via
Planner.attendee_id. They count in floor(total ÷ present); their
share is simply the part of the venue cost they never recoup.
Charging their card would route their own money back to their own
Connect account minus Stripe fees — pure waste. No Payment row is
ever created for the planner's linked attendee.
**2. The estimate is a snapshot, not a formula.** (Resolves the
parked estimated_share_cents decision.) Event.estimated_share_cents
is set to total ÷ goal at creation, may refresh while the event is
still draft, and freezes when the link is shared. Cap-and-absorb
caps at THIS number — the one attendees were actually quoted. A
mid-week venue price hike changes the actual share, never the cap.
**3. Settlement scope for the demo milestone.** settle_event
auto-closes an open event (settlement beginning closes RSVPs),
resolves unconfirmed attendance per settle_default, then per
charged attendee: ONE DB commit writing the settle-time RSVP
transition + charge_requested_at + charge_requested_cents, THEN
the Stripe call (record-first, 2026-07-13/16). One attendee's
decline or API error never aborts the others; failures land
unpaid (link minted) or dangling (retried later with the stamped
amount). Deferred, restated: the auto-settle timer, post-settle
re-marking (needs refunds — ships with walk-ins), walk-ins, the
+24h nudge, transfer-organizer.
**Testing:** transactional behavior is pinned against in-memory
SQLite (aiosqlite, dev-only) — real commits, still hermetic;
Postgres fidelity arrives with live dogfood.

## 2026-07-16: Capability-URL schema — token grain and DB bootstrap
**Context:** implementing the capability URLs (2026-07-13) for the
demo web layer forced two decisions; grilled and aligned with the
owner before any code.
**1. The RSVP capability is per attendee PER EVENT.** rsvp_token
lives on the Rsvp row, not the Attendee. "Per-attendee link minted
at RSVP" read either way; on the Attendee, one leaked or forwarded
link would change that person's RSVPs for EVERY event, past and
future — the same credential authorizing many contexts, eroding
one-token-per-purpose. On the Rsvp row a link controls exactly one
event's answer, and a returning attendee gets a fresh link per
event. Re-entering a phone on /e/ finds the same row again, so a
lost /r/ link is recoverable without accounts.
**2. Schema bootstrap is an explicit command, not startup magic.**
`python -m app.bootstrap` runs metadata.create_all; the app never
touches schema on boot. create_all only ADDS tables — it cannot
ALTER — so the dev reset story after a model change is
drop/recreate, documented beside the command. Alembic (real
migrations) arrives at live dogfood, when data must survive schema
changes.
**Mechanism:** secrets.token_urlsafe(16) — ~128-bit, 22 URL-safe
chars — as a Python-side column default, so an insert cannot forget
to mint. One column per purpose (events.event_token,
events.admin_token, rsvps.rsvp_token); each route queries ONLY its
own column, making cross-purpose reuse structurally impossible. No
collision-retry loop: the unique index converts astronomically-
unlikely (birthday bound ~1e-27 at a million rows) into
loudly-enforced.

## 2026-07-16: Public create page gated; planner account setting renamed
**Context:** live dogfood deploys the app to a public HTTPS host
(first real-money event targeted for 2026-07-29). Every event
routes charges into the planner's connected account, so an open
create page would let a stranger take card payments through the
owner's Stripe — unacceptable surface once live keys exist.
**Chose:** an env-set create password (CREATE_PASSWORD), checked
with a constant-time compare (secrets.compare_digest over
encoded bytes) on POST /events; unset = creation refused, fail
closed; the password is never echoed into a re-rendered form.
**Alternatives:** a capability create-URL (one eternal token
that lands in browser history and server logs — a password
rotates naturally and lives only in the planner's head); leaving
it open (contradicts correctness-over-speed with live keys).
**Also:** test_planner_account_id → planner_account_id
(PLANNER_ACCOUNT_ID). The live CONNECTED account id must not
live in a variable named "test", and the comment now pins the
platform-vs-connected distinction: this is the account that
RECEIVES money (transfer_data.destination), never the platform's
own id — Stripe rejects a destination of self.

## 2026-07-16: Demo-slice web layer — shape and guards
**Context:** the web layer (capability URLs → pages → settle) was
built step-by-step under align-before-acting; the grilled choices
are consolidated here so they outlive the session log.
**Shape:** server-rendered Jinja2 + form POSTs; the only browser
JS is the /r/ Payment Element island, and it is LAZY — a
SetupIntent is minted when the attendee taps "Add a card", never
on page render (/r/ is the revisit-all-week page). RSVP entry is
two-step — /e/ identifies by phone (get-or-create; re-entering a
phone recovers a lost /r/ link without accounts), /r/ answers —
because a card save needs an existing Attendee before the island
can render. The planner row is get-or-created by phone from the
create form; Connect onboarding stays a live-dogfood concern.
Buttons on /r/ are derived from the transition table, so the UI
can never offer an illegal move — a `going` attendee gets
"text the planner", not a back-out button (going →
attended|no_show only).
**Money-relevant guards:**
- A playing planner is auto-linked by phone match at RSVP
  creation (sets Planner.attendee_id) — no UI, can't be
  forgotten; this arms settle_event's never-charge-the-planner
  skip (2026-07-16 settlement mechanics).
- cancel_event refuses once ANY Payment row has left pristine
  `none` (state changed or record-first stamp set): a crashed
  settle can move money while the event is still `closed`, and
  cancelling then would stamp "nothing charged" onto a lie.
- The settle route accepts only an explicit mode (actual|cap);
  the cap button renders ONLY when actual > estimate, labeled
  with the absorbed total — silence charges actual (2026-07-15).
- Tap-to-pay links are shown once (settle report / retry result)
  and re-minted on demand — never stored (a Checkout URL goes
  stale within ~24h and a stored one would lie) and never
  re-fetched per roster load; one-payable-link-per-row stands
  (2026-07-16).
**Deferred, made explicit:** the maybe→declined auto-convert at
event start (scenarios.md) is a TIMER job and defers with the
scheduler (2026-07-13 deferred list, clarified here) — the settle
preview warns about stale maybes instead; a maybe who played taps
Going on their own link while the event is open.

## 2026-07-16: Checkout success_url threaded from the request host
**Found:** the first smoke walk on the owner's real machine (test
keys, owner's Stripe account) broke every tap-to-pay mint:
`Missing required param: success_url.` create_payment_link omitted
success_url on the assumption Stripe's hosted confirmation page
covers it; the owner's account requires the param on EVERY API
version tested (2024-04-10 through 2025-08-27.basil, via direct
API replay). The PR session's demo ran against a different account
where the omission happened to pass — an account-shaped assumption
that had to be falsified on real hardware. With the mint failing,
cardless and post-decline collection was entirely dead (settle AND
the roster's "Get fresh link").
**Chose:** success_url is a REQUIRED keyword arg of
create_payment_link, built by the WEB layer from request.base_url
(`{host}/paid`, a new static tokenless confirmation page) and
threaded through settle_event / retry_dangling / _collect and the
fresh-link route.
**Alternatives:** (a) a BASE_URL env var — rejected: a deploy that
forgets it still mints links, then dumps every payer on a
localhost redirect after their money moved; a silent
misconfiguration where threading has none. (b) Pinning a newer
Stripe API version — tested, does not lift the requirement.
**Why request.base_url:** it is the same origin share links
already use, so the proxy-headers arrangement that makes /e/
links right on a deploy makes the success page right too, with
zero new config.
**Also fixed — settle-report recovery labeling:** settle_event
collapsed every per-attendee Stripe failure to a `dangling`
outcome. But a cardless row commits `unpaid` BEFORE the mint, so a
mint failure left an unpaid row wearing a "Retry charge" button
that retry_dangling (correctly) refuses — "not a dangling charge",
recovery dead-ended. Now: state `none` at failure = `dangling`
(charge unconfirmed, same-key retry); past `none` = `unpaid`, and
the report offers "Get fresh link" — same one-payable-link
guarantees as the roster button.
**Pinned by:** the exact-kwarg contract in tests/test_payments.py,
test_checkout_success_url_from_request_host and
test_link_mint_failure_lands_unpaid_with_fresh_link in
tests/test_settle_web.py, test_paid_page_renders in
tests/test_web.py.

## 2026-07-16: Stripe id columns widened to 255 — no length contract
**Found:** minutes after the success_url fix, the SAME smoke walk
(real Postgres + real Stripe, first time both were real at once)
broke the fresh-link commit: a real Checkout Session id
(`cs_test_…`, 66 chars) overflowed stripe_checkout_session_id
VARCHAR(64) — StringDataRightTruncationError. Worse than a 500:
the session was already created at Stripe when the write died, so
a LIVE tap-to-pay link existed that the DB didn't know — exactly
the "DB knows less than Stripe" state the record-first rule
exists to prevent. (The orphan was expired by hand.) The hermetic
suite could never catch it: mocks use short ids ("cs_new") and
SQLite ignores VARCHAR lengths — this is the Postgres-fidelity
gap the 2026-07-16 settlement entry deferred, showing up early.
**Chose:** every Stripe id column (planners.stripe_account_id,
attendees.stripe_customer_id / stripe_payment_method_id,
payments.stripe_payment_intent_id / stripe_checkout_session_id)
is now String(255). Stripe publishes NO length guarantee for ids;
255 follows their own integration guidance. Existing dev DBs:
ALTER COLUMN ... TYPE VARCHAR(255) by hand or drop/recreate —
create_all never ALTERs (demo.md reset).
**Pinned by:** test_stripe_id_columns_hold_real_stripe_ids in
tests/test_app.py — introspects DECLARED capacity, so it holds on
SQLite too.

## 2026-07-21: Attendee "your events" page — view-only capability link
**Context:** attendees need a cross-event "my upcoming events" view
before 7/29, but no-accounts (2026-07-13) means no cross-event
credential exists — deliberately (2026-07-16 made rsvp_token
per-event so one leaked link touches one event).
**Alternatives:** (a) phone lookup, unverified — anyone typing any
number sees that person's schedule; refused, privacy hole. (b)
phone + SMS code — drags SMS sending into v0. (d) accounts — the
strangers-milestone answer.
**Chose:** (c) attendees.attendee_token — fourth capability token,
same minting, one column per purpose — opening GET /me/{token}:
open+closed events only, sorted by starts_at, linked from every
/r/ page. VIEW-ONLY is the load-bearing choice: no /r/ token or
link ever renders (pinned by test), so a leaked bookmark widens
what a holder SEES (your schedule) but not what they can DO
(nothing). Changing an answer still requires that event's own /r/
link — the 2026-07-16 containment stands.
**Why open+closed only:** a settled event on this page would beg
for a "pay now" button — deferred post-7/29; and the filter is by
STATE, not clock, because starts_at is display-only in v0.
**Locks in:** new column ⇒ the deployed DB's one planned
drop/recreate now rides the post-$1-test deploy; /me/ never grows
a money surface without a new decision.

## 2026-07-21: Direct payment — claim-flag, planner confirm, link-kill
**Context:** courtside reality pays by Venmo/Zelle/cash; without a
way to record it the roster lies (unpaid forever or a false
`abandoned`). In-app payment stays; this adds recording, not rails.
**Chose:** planner handles as free text (display-only, never
parsed); attendee claim = claimed_at/claimed_via FLAG on the
unpaid row, never a state — the roster counts a claim as owed
(never assume collected) until the planner's confirm performs the
existing unpaid → paid transition. mark_paid_direct expires any
live Checkout link BEFORE the state write — the INVERSE of
record-first, because the call destroys a collection path instead
of creating one (crash after expire: unpaid row + dead link,
re-mint recovers; the reverse invites double-pay) — and REFUSES
if the stored link already collected (the roster poll records it).
paid_direct_at distinguishes these rows forever: charged_cents
stays None, and the Stripe refund path never applies — planner
reverses out-of-band.
**Over-collection (the one visible case):** Stripe-paid + claim
still set — the claim deliberately survives the poll flip —
bannered to planner and attendee with "refund one" instructions.
No auto-resolution: that is refund code, and it stays guarded.

## 2026-07-21: Phone canonicalization — strict 10-digit identity
**Context:** identity in v0 IS the phone (2026-07-13), but every
lookup was exact-string: iOS autofill "(619) 555-0123" vs typed
digits minted a duplicate attendee (orphaning any saved card) and
could dodge the never-charge-the-planner match — settle would
charge the planner's own card. Both nearly bitten in the 7/21
live test (planner phone typed as an attendee row; an 11-digit
typo stored silently).
**Chose:** normalize_phone (app/phone.py): strip non-digits, drop
a leading US "1" on 11 digits, REQUIRE exactly 10 — reject at the
form with a fix-it hint. Applied at every store and compare:
create_event, get_or_create_rsvp, both sides of the planner
auto-link. Strict beats lenient: a typo caught at the form beats
a wrong identity at settle; v0 is one US metro.
**Accepted risk:** a shared-phone couple still collapses into one
attendee (divisor undercounts). Deferred on purpose — the 7/29
invite says "each person uses their own number"; a
confirm-identity step is a post-7/29 fork.

## 2026-07-21: Uniform RSVP rule — any answer to any answer while open
**Amends** the RSVP machine and retires the 2026-07-16 "backing
out is planner territory" note — a hold-era fossil: backing out
used to mean releasing a hold; with charge-at-close it just means
changing your mind before close. Adds going → maybe|declined and
declined → maybe: the answer set {going, maybe, declined} is now
mutually reachable while the event is open (pending → any, as
before). The open-event guard already scopes every change;
attended/no_show stay planner-only writes at settlement, and the
CHOICES membership check still blocks a crafted self-"attended"
POST. UI followed with no template change — buttons derive from
the table (allowed_choices), so a going attendee gains Maybe and
Can't-make-it instead of "text the planner".

## 2026-07-21: Sub-50¢ shares refused before any stamp
**Found (phone walk 2026-07-19):** Stripe refuses charges under
50¢ — a $1÷3 test event landed every charge dangling and link
mints failed with no explanation. **Chose:** settle_event raises
BEFORE any record-first stamp or present-marking when a nonzero
per-person charge is under MIN_CHARGE_CENTS (app/payments.py);
the settle preview mirrors the guard (no settle button it would
refuse; the cap button hides when the estimate is under 50¢).
Service-level on purpose — a UI-only guard lets a direct POST
through. Deliberately NOT a floor in _validate_cents: a future
partial refund can legitimately be under 50¢. Settling a $0
share (charge nobody) stays valid.
