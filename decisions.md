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
