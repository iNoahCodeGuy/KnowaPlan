# State machines

Executable transcription: app/state_machines.py, kept in sync by
tests/test_state_machines.py. On disagreement, this doc wins.

## Event
draft → open → closed → settled → archived
                  ↓
              cancelled

- draft: planner is editing, link not yet shared
- open: link shared, accepting RSVPs (card optional)
- closed: RSVPs locked, event happening now or recently
- settled: attendance marked, charges complete (auto-charges made,
  tap-to-pay links sent)
- archived: 72h after settlement, read-only
- cancelled: planner cancelled before settlement; nothing charged (no
  holds to void)

Transitions:
- draft → open: planner shares link
- open → closed: planner closes RSVPs manually, OR automatically when
  settlement begins (planner starts marking attendance, or the settle
  timer fires). NOT tied to event start — RSVPs and new joins stay
  open through the game (decisions.md 2026-07-15)
- closed → settled: manual (planner marks attendance) OR automatic
  (timer fires per planner's setting at event creation)
- settled → archived: automatic, 72h after settled
- open|closed → cancelled: planner action; nothing charged (no holds).
  After settlement, reversals go through Payment paid → refunded, not
  cancellation

## RSVP
pending → going → attended | no_show
       → maybe → going | declined
       → declined → going (while event still open)

- pending: invitee clicked link but hasn't responded
- going: said yes. A card on file is OPTIONAL and tracked on the
  Payment row, not here — a `going` attendee may or may not have saved
  a card (decisions.md 2026-07-15); the roster shows whether they have
- maybe: tentative; converts on reminder or by deadline
- declined: said no; may still convert to going while the event is
  open — no card required to say going (a card is optional and, if
  added, charged at close). Not terminal
- attended: planner marked present; their share is charged at close
- no_show: planner marked absent; nothing charged (no hold to void)

## Payment (per attendee per event)
none → paid → refunded
   ↘ unpaid → paid
            → abandoned

Charge-at-close (decisions.md 2026-07-15): no authorization, no hold.
The share is charged at close from a card saved at RSVP, or collected
via a tap-to-pay link.

- none: no charge yet. Also the terminal state for no-shows and events
  cancelled before close — nothing owed, nothing charged
- paid: the attendee's actual share was charged — automatically from a
  card saved at RSVP, via the tap-to-pay link, or by the planner
  confirming a direct payment (Venmo/Zelle/cash; paid_direct_at set,
  charged_cents stays empty — Stripe collected nothing, so the Stripe
  refund path never applies to these rows). Terminal except for
  refund
- unpaid: close happened and the share was not collected — no card on
  file, or a saved-card charge declined off-session at close. The
  planner sends a tap-to-pay link (one auto-nudge at +24h, then on
  demand). Shows on the roster. Not terminal. May carry an attendee
  claim ("I paid the planner directly" — a flag, never a state): the
  row still counts as owed until the planner's confirming tap
  performs unpaid → paid
- abandoned: the planner stopped chasing. Terminal
- refunded: reversal of a collected charge — planner discretion, or a
  re-split after a late walk-in lowered shares AFTER a charge landed.
  Terminal

Transitions:
- none → paid: card on file, charged successfully at close
- none → unpaid: close with no card, or a saved-card charge declined
- unpaid → paid: attendee pays via the tap-to-pay link, OR the
  planner confirms a direct payment (any live link is expired
  BEFORE the state write — a paid row must never leave a live
  collection path behind)
- unpaid → abandoned: planner stops chasing
- paid → refunded: reverse a collected charge

A charge that lands `unpaid` is collected via the tap-to-pay link on
the SAME Payment row — the saved card is never re-fired for this row
(the link is the only recovery; decisions.md 2026-07-16). "Same
idempotency key on retry" applies to the dangling case only: stamp
set, Stripe never answered. A genuinely new attempt (e.g. a re-added
attendee) is a new row with the next attempt number (decisions.md
2026-07-08, still in force).

Mechanism — record-first (decisions.md 2026-07-13, adapted): the
charge stamps intent (a charge-requested timestamp and the intended
amount — decisions.md 2026-07-16) in the same DB transaction as the
matching attendance change, BEFORE the Stripe call;
the terminal state is written after Stripe answers. A dangling charge
(stamp set, state still none) is queryable, surfaced to the planner,
and retried with the SAME idempotency key. The DB always knows at
least as much as Stripe.

Superseded by the 2026-07-15 pivot: `authorized`, `voided`,
`auth_failed`, `failed → resolved`, the capture-≤-hold ceiling, and
the release-vs-refund distinction — all belonged to the hold model and
no longer exist. No holds means no authorization to place, expire, or
void.

Deferred (v0):
- 3DS/SCA on an off-session charge: a saved-card charge at close can in
  principle require the customer present. Rare for US friend-group
  cards; if it trips, the attendee falls to `unpaid` and pays via the
  link (which is on-session). Not separately modeled in v0

## Attendance
unconfirmed → present | absent

- unconfirmed: event not yet settled
- present: planner marked attended OR auto-defaulted to attended
  via settlement default; charge eligible
- absent: planner marked absent OR auto-defaulted to absent via
  settlement default; not charged (no hold to void)

  