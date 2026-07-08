# Scenarios

## Planner can't attend but group wants to continue
- Planner opens event, taps "Transfer organizer"
- Selects an attendee in `going_paid` state
- New planner inherits event ownership
- Original planner: if `going_paid`, void their authorization
  (Payment → `voided`); mark RSVP as `declined`
- Event proceeds normally under new owner

## Attendee shows up but didn't RSVP/pay
- During 72h settlement window, planner marks them `present`
- App generates a payment link for the post-event per-person amount
- Sent via SMS to the phone number planner provides
- Walk-in payment is a direct immediate charge (none → captured, no
  prior authorization) — a separate flow from the RSVP authorize-
  then-capture path, not a capture of an existing hold
- Reconciliation re-runs across all attendees, ideally before any
  captures. A walk-in lowers each per-person share (fixed court cost
  ÷ more people): for attendees not yet captured, capture the new
  lower share; for any already captured at the old higher share, the
  overage is owed back as a refund (a genuine refund — money was
  captured)

## Maybe doesn't convert by deadline
- 24h before event: final reminder sent
- At event start time: maybe auto-converts to declined
- They can still tap "Going" until event is closed (treated as a late
  RSVP); converting to Going requires a card authorization at that
  point, same as any RSVP

## Late RSVP after planner closes RSVPs
- If event is in `closed` state but not yet started: planner gets a
  notification, can manually approve, late attendee gets authorized
- If event has already started: redirect to "this event is in progress"
  page with option to be added as a walk-in (treated like attended-but-unpaid)

## Cost changes between RSVP and event
- Triggered when venue raises the rate, or planner reschedules to a
  more expensive slot, between RSVP and event
- If new per-person share ≤ original authorized worst-case: capture at
  new actual share, no extra action needed
- If new per-person share > authorized: capture at the authorized
  amount (can't exceed it); planner eats the delta OR sends SMS
  settle-up links for the difference
- v0: no in-app handling for the over-cost case; planner negotiates
  out-of-band

## Attendee confused by card hold ("you charged me already?!")
- Statement line for the authorization can look like a charge to
  attendees unfamiliar with manual-capture flows
- Event page, RSVP confirmation, and post-RSVP SMS all carry the
  same line: "This is a hold, not a charge. We'll only charge your
  actual share after the game — usually around $X."
- After settlement, the released portion of the hold may still show
  as pending on the attendee's statement for 1–7 days — the issuing
  bank releases it on its own timeline, not ours; say so to preempt
  the follow-up question
- FAQ link in confirmations explains authorization vs capture in
  more detail
- v0: no live support flow; planner handles individual questions
  via text

## Card declined at capture time
- Mark payment `failed`
- Send attendee a "settle up" link via SMS
- 7-day grace period to resolve
- After 7 days, planner gets notified to chase manually

## Planner doesn't mark attendance (auto-settle backstop)
- Settle target = the planner's configured timing (end-of-event-day,
  +24h, +48h, or +6 days), chosen at event creation, mutable until
  the settle process begins
- Effective backstop = min(settle target, earliest authorization
  expiry across attendees). Authorizations expire 7 days after they
  are created (Extended Authorization deferred — see decisions.md
  2026-05-26), so an event with early RSVPs can force the backstop
  earlier than the planner's chosen target. The backstop must never
  fall after any attendee's auth expiry, or that capture is lost
- Reminders re-anchor to the effective backstop: a reminder ~24h
  before it, and a final SMS ~24h before it fires
- Final SMS reflects the planner's default: "auto-charging tomorrow"
  if assume-all-attended, "auto-voiding tomorrow" if void-all
- At the backstop: auto-settle fires per the planner's pre-set
  default (assume-all-attended OR void-all)
- After auto-settle: standard 72h edit window applies; planner can
  still re-mark and captures adjust accordingly

## Attendee disputes attendance ("I was there!")
- For v0: handled out-of-band via SMS between planner and attendee
- Planner can edit attendance for 72h
- After 72h, event is locked
- (Future: in-app dispute flow — out of scope for v0)