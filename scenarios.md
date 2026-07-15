# Scenarios

## Planner can't attend but group wants to continue
- Planner opens event, taps "Transfer organizer"
- Selects an attendee to hand ownership to
- New planner inherits event ownership
- Original planner: if no longer attending, mark their RSVP `declined`
  (or `no_show` at settlement) — nothing to void, since no hold was
  ever placed. If they DID attend, they are charged their share at
  close like anyone else
- Event proceeds normally under the new owner

## Attendee shows up but didn't RSVP/pay
- During the 72h settlement window, planner marks them `present`
- If they add a card, it is charged for their share at close; if not,
  the planner sends a tap-to-pay link (same as any cardless attendee)
- A walk-in is not a special payment path anymore — with no holds,
  everyone is a charge-at-close, so a walk-in is just a late `present`
  attendee
- A walk-in lowers each per-person share (fixed court cost ÷ more
  people). Re-split BEFORE charging where possible: charge the new
  lower share. For anyone already charged at the old higher share, the
  overage is refunded (a genuine refund — money was collected)

## Maybe doesn't convert by deadline
- 24h before event: final reminder (from the planner's phone)
- At event start time: maybe auto-converts to declined
- They can still tap "Going" until the planner closes RSVPs — which,
  since RSVPs stay open through the game, can be during or just after
  play. Adding a card is optional; if added, it is charged at close

## Late RSVP / joining late
- RSVPs stay OPEN through the game (decisions.md 2026-07-15), so a
  latecomer or a brought friend just taps Going and (optionally) adds
  a card — no planner approval gate, no "event in progress" wall
- They lower everyone's share by joining; the split is computed at
  close from whoever is marked present
- Once the planner closes RSVPs (or the event settles), a stale link
  shows "this event is closed / settled"

## Cost changes between RSVP and event
- Triggered when the venue raises the rate, or the planner reschedules
  to a pricier slot
- The split is computed at close, so a cost change simply changes the
  number everyone is charged — there is no hold ceiling to bump into
- If the new share exceeds the estimate shown at RSVP, the planner
  chooses at settlement: charge the true (higher) share, or cap at the
  estimate and absorb the difference (default: charge actual)

## Fewer than the goal attendance show up
- The estimate shown at RSVP is total ÷ goal attendance
  (decisions.md 2026-07-15); it sizes no hold
- If fewer than the goal show up, the true share is higher than the
  estimate. The planner chooses at settlement: charge the true share,
  or cap at the estimate and absorb the gap (default: charge actual)
- The settlement screen shows the shortfall explicitly (gap ×
  attendees) — never absorbs it silently
- Goal attendance is the planner's expectation dial, set at creation

## Share doesn't divide evenly
- Everyone is charged floor(total cost / headcount); the planner
  absorbs the remainder — at most headcount − 1 cents per event
- Nobody is ever charged a cent more than anyone else

## Attendee asks when they'll be charged
- With no holds, nothing appears on the attendee's statement until the
  charge at close — there is no pre-event "hold" to mistake for a
  charge
- Set expectation at RSVP: "Your card is saved. We'll charge only your
  actual share after the game — usually around $X. Nothing is charged
  now."
- Cardless attendees are told they'll get a tap-to-pay link after the
  game
- v0: no live support flow; planner handles individual questions by
  text

## Card fails to save at RSVP
- Attendee taps Going, enters a card, the SetupIntent fails
- No money was at stake (a save, not a charge). Prompt an immediate
  retry with another card, or let them proceed cardless (they'll get a
  tap-to-pay link at close)
- The roster shows them as no-card until a card saves or they pay a
  link

## Saved-card charge declines at close
- The saved card is charged for the share at close and the issuer
  declines (expired, insufficient, off-session block)
- Payment goes `unpaid`; the planner sends a tap-to-pay link (which is
  on-session and clears most off-session declines)
- One auto-nudge at +24h prompts the planner to remind; after that the
  balance sits on the roster and the planner nudges on demand
- If never paid, the planner marks it `abandoned` and chases
  out-of-band

## Planner doesn't mark attendance (auto-settle backstop)
- Settle target = the planner's configured timing (end-of-event-day,
  +24h, +48h, or +6 days), chosen at creation, mutable until settling
  begins
- With no holds there is no auth-expiry bound — the backstop is simply
  the planner's settle target (decisions.md 2026-07-15 supersedes the
  expiry-bounded backstop of 2026-05-28)
- A reminder ~24h before the backstop, from the planner's phone
- At the backstop: auto-settle fires per the planner's pre-set default
  (assume-all-attended → charge everyone's share; or mark-all-absent →
  charge nobody)
- Actual > estimate under auto-settle defaults to charging the actual
  share (no planner present to choose otherwise)
- After auto-settle: standard 72h edit window applies; the planner can
  re-mark and charges adjust (a new charge, or a refund if someone was
  over-charged)

## Attendee disputes attendance ("I was there!")
- For v0: handled out-of-band via SMS between planner and attendee
- Planner can edit attendance for 72h
- After 72h, the event is locked
- (Future: in-app dispute flow — out of scope for v0)
