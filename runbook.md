# Day-of runbook — first live event (club meeting, 2026-07-29)

The planner's crib sheet for running a real-money event, written
for a phone at the court. Assumes the live flip already happened
(demo.md §Live flip) and the $1 test passed. Numbers below use the
club meeting's expected split: **$130 court, goal 15 → $8.66
estimate**.

## Morning of

1. **Know the real total first.** There is NO edit-event screen in
   v1 — the total cost is fixed at creation. Wrong total before
   you've tapped Open RSVPs? Just create a fresh event and ignore
   the old draft — a draft can't be cancelled and doesn't need to
   be (its link was never shared). Once RSVPs are open, the admin
   page has a Cancel button — available until the first charge is
   ATTEMPTED (even a crashed attempt locks it), then corrections
   are dashboard refunds.
2. Create the event at `https://<domain>/`: total cost `130`,
   goal attendance `15`, your settle default, your CREATE_PASSWORD.
3. **Bookmark the admin page.** That link IS your planner
   credential — whoever holds it is the planner. Don't text it to
   anyone.
4. Tap **Open RSVPs**, copy the share link, and text the group.
   Suggested invite (pushes card-save — every saved card is one
   less person to chase):

   > Pickleball Wednesday! RSVP here: `<share link>`
   > Save a card when you RSVP — nothing is charged now. Your
   > exact share (~$8.66 of the $130 court) is charged
   > automatically after we play. No card? I'll text you a pay
   > link after.

## Before and during play

- RSVPs stay open through the game — late arrivals and brought
  friends just tap Going on the share link (they LOWER everyone's
  share).
- If you're playing, RSVP yourself with the same phone number you
  used on the create form. The roster will show "you — never
  charged": you're part of the split but the app never charges the
  planner's own card.
- Lost RSVP link: re-entering the same phone number on the share
  link recovers it — same person, same page.
- The roster shows who has a card saved vs. who will need a pay
  link — glance at it before play so the after-game chase isn't a
  surprise.

## After play, at the court (the part that matters)

Settlement is **one-shot** in v1: once you settle there is no
re-marking in the app, and corrections are manual refunds from the
Stripe dashboard. So go slowly here — it's two minutes.

1. **Sweep the maybes FIRST — before you close RSVPs.** Closing
   RSVPs is permanent: after it, a `maybe` can no longer tap
   Going, can't be marked present, and silently drops out of the
   split (everyone else pays more; the maybe pays nothing). So
   while the event is still open, scan the roster's Answer column —
   anyone still `maybe` (or `declined`) who actually played taps
   Going on their own link NOW.
2. **Close RSVPs, then mark.** Tap **Close RSVPs** to lock the
   list — marking is off until you do, so a stray tap can't end
   RSVPs early. The **present**/**absent** buttons appear on each
   row once it's closed. Look around the court while you mark —
   did everyone who played get marked?
3. Tap **Settle up** and READ the preview:
   - the participant count and per-head share,
   - what your settle default will do to anyone you left unmarked,
   - how many are still `maybe` (a count — the roster shows who).
     They won't be charged. If a maybe PLAYED and you're seeing
     this after the close, the app can't add them back: settle
     without them and square up outside the app, or cancel the
     event (still possible — nothing charged yet) and start over
     with everyone re-RSVPing. The step-1 sweep exists so you
     never face that choice.
4. Pick the charge mode:
   - If everyone showed (15 present): share is $8.66, matches the
     estimate — one button, **Settle now**.
   - If fewer showed, the true share is higher and TWO buttons
     appear: **Charge actual shares** (default — e.g. 13 present →
     $10.00 each) or **cap at the $8.66 estimate and absorb the
     gap yourself** (the button shows the exact total you'd eat).
     Absorbing is generosity, never the default.
5. The settle report shows each person's outcome:
   - `paid` — saved card charged, done;
   - `unpaid` with a **pay link** — text it with the button next
     to it. Links are shown ONCE; if you lose one, the roster's
     **Get fresh link** mints a replacement (the old one is
     retired — nobody can pay twice);
   - `dangling` — the app crashed mid-charge (the roster shows the
     same row as "charge requested — unconfirmed"). Tap **Retry
     charge** right away: a prompt retry replays the exact same
     request, so it can't double-charge. That guarantee fades
     after ~a day — if a row has sat unconfirmed overnight, do
     NOT just retry: first check dashboard.stripe.com → Payments
     for a charge of that amount, and only retry if nothing
     landed.

## Collecting afterward

- **Reload the roster to see payments land** — there's no push;
  the page checks outstanding links each time it loads.
- Quick split table ($130 total):

  | present | each pays |
  |---|---|
  | 15 | $8.66 |
  | 14 | $9.28 |
  | 13 | $10.00 |
  | 12 | $10.83 |
  | 11 | $11.81 |
  | 10 | $13.00 |

  (Everyone pays the same rounded-down amount; you absorb the
  leftover cents — always less than 1¢ per player, e.g. 10¢ when
  15 play.)

## When something goes wrong

- **A saved card declines at settle** — expected sometimes. The
  row lands `unpaid` with the decline reason and a pay link; text
  the link (it clears most off-session declines because the
  person is present for it).
- **Someone ghosts the link** — the balance just sits on the
  roster. Nudge by text when you feel like it; if they never pay,
  the row simply stays `unpaid` (v1 has no write-off button) and
  you chase in person.
- **You mis-marked someone / overcharged someone** — refund from
  the Stripe dashboard, not the app: dashboard.stripe.com →
  Payments → find the charge (search the amount) → Refund. The
  money returns to their card in ~5–10 business days.
- **Anything looks stuck** — screenshot the roster and stop
  tapping. The database records intent before money moves, so a
  stuck state is recoverable; a flurry of retries just makes the
  story harder to read. (A prompt Retry charge is safe; one
  that's sat overnight needs the dashboard check above first.)

## Cheat sheet

| Moment | Action |
|---|---|
| Morning | Create ($130 / 15), bookmark admin, Open RSVPs, text invite |
| At court | Sweep maybes → Close RSVPs → mark present/absent → read preview → settle ONCE |
| Cardless | Text each pay link from the report |
| Later | Reload roster to watch payments land |
| Mistake | Stripe dashboard → Payments → Refund |
