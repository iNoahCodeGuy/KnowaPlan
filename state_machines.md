# State machines

Executable transcription: app/state_machines.py, kept in sync by
tests/test_state_machines.py. On disagreement, this doc wins.

## Event
draft → open → closed → settled → archived
                  ↓
              cancelled

- draft: planner is editing, link not yet shared
- open: link shared, accepting RSVPs and authorizations
- closed: RSVPs locked, event happening now or recently
- settled: attendance marked, captures and voids complete
- archived: 72h after settlement, read-only
- cancelled: planner cancelled before settlement; all auths voided,
  no captures

Transitions:
- draft → open: planner shares link
- open → closed: automatic at event start time
- closed → settled: manual (planner marks attendance) OR automatic
  (timer fires per planner's setting at event creation)
- settled → archived: automatic, 72h after settled
- open|closed → cancelled: planner action; auths voided immediately,
  no captures. After settlement, reversals go through Payment
  captured → refunded, not cancellation

## RSVP
pending → going → going_paid → attended | no_show
       → maybe → going | declined
       → declined → going (while event still open)

- pending: invitee clicked link but hasn't responded
- going: said yes, card authorized
- going_paid: said yes, card authorized successfully
- maybe: tentative; converted on reminder or by deadline
- declined: said no; may still convert to going while the event is
  open — requires a fresh card authorization, same as any RSVP
  (decisions.md 2026-07-08). Not terminal
- attended: planner marked present, capture executed
- no_show: planner marked absent, authorization voided

## Payment (per attendee per event)
none → authorized → captured → refunded
                 ↘ voided
                 ↘ failed → resolved
                          → abandoned

- none: no card on file yet
- authorized: PaymentIntent created with manual capture; hold placed
  for the worst-case share
- captured: actual share charged (≤ authorized). Capturing less than
  the authorized worst-case RELEASES the uncaptured remainder
  automatically — this is NOT a refund and produces no Refund object
- voided: authorization released without any capture — no-show,
  attendee removed before capture, event cancelled before capture, or
  the 7-day auth window expired. No money moved. Terminal
- refunded: reversal of an already-captured charge only (event
  cancelled after capture, or planner discretion). Terminal
- failed: capture attempt failed (card declined, expired, etc.)
- resolved: post-failure payment completed via SMS settle-up link
- abandoned: 7-day grace period expired; planner notified to chase
  manually

Transitions:
- none → authorized: RSVP accepted, card authorized (hold placed)
- authorized → captured: attendance confirmed; capture actual share
- authorized → voided: no-show, removed pre-capture, event cancelled
  pre-capture, or auth window expired
- authorized → failed: capture attempted but declined/expired
- captured → refunded: reverse an already-captured charge
- failed → resolved: attendee pays via SMS settle-up link
- failed → abandoned: 7-day grace expired, still unpaid

Re-authorization after a terminal state (voided, abandoned) is a NEW
payment instance — the next attempt row — not a transition out of a
terminal state (decisions.md 2026-07-08).

Deferred (v0) — revisit before opening to strangers:
- requires_action: a 3DS/SCA challenge can occur on authorize. Not
  modeled in v0 (friend-group cards rarely trigger it). When added,
  it sits between none and authorized
- Walk-in direct charge (none → captured, no prior authorization —
  see scenarios.md): documented but not built in v0. Add the
  none → captured transition when walk-ins ship

## Attendance
unconfirmed → present | absent

- unconfirmed: event not yet settled
- present: planner marked attended OR auto-defaulted to attended
  via settlement default; capture eligible
- absent: planner marked absent OR auto-defaulted to absent via
  settlement default; authorization voided