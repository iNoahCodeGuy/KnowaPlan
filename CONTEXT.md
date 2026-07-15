# KnowaPlan

The shared language of KnowaPlan. When attendees split the cost of a
booking (a pickleball court), these are the words we use — and the ones
we deliberately avoid — so the docs, the code, and the conversation all
mean the same thing.

This is a **glossary, not a spec**. It says what each word *means*, not
how the feature works. For the "how," read `state_machines.md`,
`scenarios.md`, and `decisions.md`.

New to the project? Read the terms top to bottom once — they build on
each other.

## Language

### People

**Planner**:
The person who creates an Event and collects the money. They are the
merchant of record (funds land in their Stripe account). One Planner
per Event.
_Avoid_: Organizer, host, admin, owner.

**Attendee**:
A person invited to an Event. They RSVP, may save a card, and are
charged their Share if they attend.
_Avoid_: Guest, user, member, player.

### The thing being planned

**Event**:
One shared-cost outing — a single court booking that a group splits.
Holds the total cost and the Planner's Goal Attendance.
_Avoid_: Game, session, booking, meetup.

**RSVP**:
One Attendee's answer for one Event (going / maybe / declined, then
attended / no_show). It records *intent to show up* — never money.
Whether they saved a card lives on the Payment, not here.
_Avoid_: Reply, response, invite.

**Payment**:
The money record for one Attendee at one Event: has their Share been
collected? Separate from the RSVP on purpose — saying "going" and
paying are two different facts.
_Avoid_: Charge (a charge is one Stripe event; a Payment is the whole
record), bill, transaction.

### The two moments that end an Event

These are different, and mixing them up is the classic beginner
mistake. **No money moves at Close. Money moves at Settlement.**

**Close**:
The Planner locks RSVPs — the Event goes `open → closed`. RSVPs and
late joins stop being accepted. **Nothing is charged.** Attendance is
not marked yet.
_Avoid_: using "close" to mean the charging moment (that's Settlement).

**Settlement** (verb: **settle**):
The Planner marks who was present, the split locks at
`floor(total ÷ present)`, and the charges fire — the Event goes
`closed → settled`. **This is where money moves.** Can also fire
automatically via the settle backstop if the Planner never acts.
_Avoid_: closing, finalizing, checkout.

### Money words

**Charge-at-close**:
The name of KnowaPlan's money model: **no card holds**. A card is
*optional* at RSVP; each Attendee's real Share is charged at
Settlement — from a saved card, or via a Tap-to-pay link. The "close"
in the name is the informal end-of-event moment, which the state
machine realizes as Settlement (see above). Replaced the old
hold-and-capture model on 2026-07-15.
_Avoid_: hold, authorization, capture (those belonged to the retired
model).

**Share**:
What one Attendee owes for one Event: `floor(total cost ÷ number
marked present)`. Everyone present pays the same whole-cent amount;
the Planner absorbs any remainder (at most headcount − 1 cents).
_Avoid_: split (the split is the *act* of dividing; a Share is one
person's slice), portion, cut.

**Estimate**:
The rough per-person number shown at RSVP: `total ÷ goal attendance`.
Display and expectation only — it sizes no hold and is not what gets
charged. The real number is the Share, computed at Settlement.
_Avoid_: quote, price, cost (until it's the actual Share, it's just an
Estimate).

**Goal attendance**:
The Planner's expected headcount, set when the Event is created. Its
only job is to compute the Estimate. It does **not** decide the
Share — the count of people marked present does.
_Avoid_: capacity, minimum, headcount (headcount is the actual number
present; goal attendance is the guess).

**Saved card**:
A card an Attendee stores at RSVP so it can be charged later. Stored
via a Stripe SetupIntent — a *save*, not a charge and not a hold. No
money moves when a card is saved.
_Avoid_: card on file is fine; do not call it a "hold" or a "charge."

**Tap-to-pay link**:
A one-time payment link the Planner sends to collect a Share from
someone with no Saved card (or whose Saved card declined at
Settlement). Tapping it shows a confirm screen before charging.
_Avoid_: invoice, bill, payment request.

### How Attendees reach the app

**Capability URL**:
An unguessable link that is the *only* credential — there are no
accounts or passwords in v0. Three kinds, never reused across
purposes: the **event link** (Planner shares it; anyone can view and
start an RSVP), the **RSVP link** (per-Attendee; lets that one person
change their own RSVP), and the **admin link** (per-Event; lets the
Planner mark attendance, settle, and cancel). Whoever holds a link
*is* that role.
_Avoid_: login, session, token (in user-facing terms — "token" is fine
when talking about the raw value in the DB).
