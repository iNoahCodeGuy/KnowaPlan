# Test-mode demo — the full slice, played solo

The 2026-07-13 milestone: create event → share link → RSVP (card
optional) → close → mark attendance → settle → collected, with
Stripe test tokens and you playing every role. Nothing here moves
real money.

## One-time setup

1. Postgres running locally, then:

       createdb knowaplan

2. `.env` at the repo root (gitignored):

       STRIPE_SECRET_KEY=sk_test_...
       STRIPE_PUBLISHABLE_KEY=pk_test_...
       PLANNER_ACCOUNT_ID=acct_...
       CREATE_PASSWORD=pick-something
       # optional; this is the default:
       # DATABASE_URL=postgresql+asyncpg://localhost:5432/knowaplan

   PLANNER_ACCOUNT_ID is the CONNECTED account — the Stripe
   Connect (Standard) account that RECEIVES the money — NOT the
   platform's own account id (Stripe refuses a destination of
   self). Test-mode connected acct here; the live one arrives at
   live dogfood. CREATE_PASSWORD gates the public create page:
   without it, event creation is refused (fail closed).

3. Create the schema, boot the app:

       .venv/bin/python -m app.bootstrap
       .venv/bin/uvicorn app.main:app --reload

## The walk

Use a second browser window (or incognito) whenever you switch
from planner to attendee — the links are the only identity.

1. **Create**: http://localhost:8000/ — you're the planner
   (enter your CREATE_PASSWORD in the form's password field).
   Total cost 120, goal 4 → the group sees a $30.00 estimate.
   You land on the admin page: **bookmark it** (whoever holds the
   admin link IS the planner).
2. **Open**: tap "Open RSVPs". Copy the share link — in real
   life you'd text it; here, open it as each attendee.
3. **RSVP as attendees** (distinct phones — phone is identity):
   - Attendee A: Going, then "Add a card" with
     `4242 4242 4242 4242` (any future expiry / CVC / ZIP) —
     saves clean, charges clean at close.
   - Attendee B: Going, card `4000 0000 0000 0341` — SAVES fine
     but DECLINES when charged: this demos the
     saved-card-declines-at-close → unpaid → link recovery path.
   - Attendee C: Going, no card — the tap-to-pay path.
   - Yourself: RSVP with your PLANNER phone — the roster shows
     "you — never charged": you're in the divisor, never a
     charge (decisions.md 2026-07-16).
   - Optional: card `4000 0025 0000 3155` triggers a 3DS
     challenge at save — exercises the redirect leg of the
     card-save finalize.
   - Lost /r/ link? Re-enter the same phone on the share link —
     same row, same page.
4. **Mark attendance** on the admin roster (the first mark
   closes RSVPs automatically). Mark fewer people present than
   your goal to make the true share exceed the estimate — that's
   what makes the cap-and-absorb choice appear at settle.
5. **Settle up**: read the preview — the split, what your
   settle default will do to unmarked rows, who's still maybe.
   Choose: charge actual (default) or cap at the estimate and
   absorb the difference. The report shows, per attendee:
   - A: `paid` (off-session charge landed),
   - B: `unpaid` + decline reason + a tap-to-pay link,
   - C: `unpaid` + a tap-to-pay link,
   - links are SHOWN ONCE — re-mint from the roster if lost.
6. **Collect**: open a tap-to-pay link, pay it with
   `4242 4242 4242 4242` on Stripe's hosted page, then reload
   the roster — the on-load poll flips the row to `paid`
   (no webhooks in v0; decisions.md 2026-07-13).
7. **Dangling rows**: if a charge is interrupted between the
   record-first stamp and Stripe's answer, the roster shows
   "charge requested — unconfirmed" with a Retry button; the
   retry re-sends the STAMPED amount under the SAME idempotency
   key, so it can never double-charge.

## Reset between runs

    dropdb knowaplan && createdb knowaplan
    .venv/bin/python -m app.bootstrap

(create_all only ADDS tables — after any model change this
drop/recreate IS the migration story until live dogfood brings
Alembic.)

## If it refuses loudly

| Symptom | Fix |
| --- | --- |
| Event create: "CREATE_PASSWORD is not configured" | Set it in `.env`; restart uvicorn |
| Event create: "wrong create password" | Type the CREATE_PASSWORD value into the form's password field |
| Event create: "PLANNER_ACCOUNT_ID is not configured" | Set it in `.env`; restart uvicorn |
| "Add a card": STRIPE_SECRET_KEY error | Set the test secret key in `.env` |
| /r/ says card saving isn't configured | Set STRIPE_PUBLISHABLE_KEY in `.env` |
| Charge fails mentioning transfer/destination | PLANNER_ACCOUNT_ID isn't a CONNECTED Standard account on this platform (or is the platform's own id) |
