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

## Deployed (Railway) — for links real phones can open

Texted /e/, /r/, and tap-to-pay flows need a public HTTPS URL
(Stripe also requires HTTPS for live-mode card pages). Steps:

1. railway.com → New Project → **Deploy from GitHub repo** →
   pick this repo (it auto-detects the Dockerfile). Point it at
   the branch you're testing.
2. In the project: **New → Database → PostgreSQL**.
3. On the APP service → Variables, set:

   | Variable | Value |
   | --- | --- |
   | DATABASE_URL | the Postgres service's URL with the scheme rewritten: `postgresql://…` → `postgresql+asyncpg://…` (keep the private `…railway.internal` host) |
   | STRIPE_SECRET_KEY | `sk_test_…` — TEST keys until the live flip |
   | STRIPE_PUBLISHABLE_KEY | `pk_test_…` |
   | PLANNER_ACCOUNT_ID | test-mode CONNECTED account until the live flip |
   | CREATE_PASSWORD | pick something; unset = creation locked |

4. Service → Settings → Networking → **Generate Domain** → your
   public https URL.
5. Create the schema EXPLICITLY (never on startup): from your
   local checkout,

       DATABASE_URL="postgresql+asyncpg://<public PG url>" \
         .venv/bin/python -m app.bootstrap

   (the Postgres service's PUBLIC url, same scheme rewrite), or
   `railway ssh` into the app service and run
   `python -m app.bootstrap` there (private url already set).
6. Verify: `https://<domain>/health` → `{"status":"ok"}`, then
   walk the full test-mode demo above ON the public domain from
   a real phone.

The Dockerfile starts uvicorn with `--proxy-headers
--forwarded-allow-ips '*'` — that is what makes the share links
the roster prints carry the real https domain instead of an
internal hostname. If links ever print `http://` or a weird
host, that flag got lost.

**Live flip** (the $1 test, then the real event): swap
STRIPE_SECRET_KEY / STRIPE_PUBLISHABLE_KEY to live keys and
PLANNER_ACCOUNT_ID to the LIVE connected account, restart the
service — no code change. Refunds during the live test are made
from the Stripe DASHBOARD (in-app refunds ship with walk-ins).

## If it refuses loudly

| Symptom | Fix |
| --- | --- |
| Event create: "CREATE_PASSWORD is not configured" | Set it in `.env`; restart uvicorn |
| Event create: "wrong create password" | Type the CREATE_PASSWORD value into the form's password field |
| Event create: "PLANNER_ACCOUNT_ID is not configured" | Set it in `.env`; restart uvicorn |
| "Add a card": STRIPE_SECRET_KEY error | Set the test secret key in `.env` |
| /r/ says card saving isn't configured | Set STRIPE_PUBLISHABLE_KEY in `.env` |
| Charge fails mentioning transfer/destination | PLANNER_ACCOUNT_ID isn't a CONNECTED Standard account on this platform (or is the platform's own id) |
