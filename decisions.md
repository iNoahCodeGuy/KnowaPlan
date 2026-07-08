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
