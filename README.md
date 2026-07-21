# KnowaPlan

**Split the cost of a group event fairly, and collect everyone's real
share after it happens — without anyone getting stiffed by a bad
estimate.**

You book a $130 pickleball court. Twelve people say they're coming.
How much does each person actually owe, and how do you collect it
without chasing everyone over Venmo for a week? KnowaPlan is the
answer: attendees RSVP through a texted link and (optionally) save a
card; after the game the organizer marks who actually showed up, and
the app charges each person their exact share — automatically from the
saved card, or via a tap-to-pay link for anyone cardless.

> **This app custodies real money.** The guiding rule of the whole
> codebase is **correctness over speed**. If you're about to change
> anything under `app/payments.py`, `app/settlement.py`,
> `app/state_machines.py`, or `app/models.py`, read
> [Money-handling rules](#10-money-handling-rules-non-negotiable) first —
> those rules are non-negotiable and some are enforced by an automated
> guard.

---

## Table of contents

1. [What it does (in plain terms)](#1-what-it-does-in-plain-terms)
2. [Project status & scope](#2-project-status--scope)
3. [Quick start](#3-quick-start)
4. [The one idea to understand first: charge-at-close](#4-the-one-idea-to-understand-first-charge-at-close)
5. [Architecture: the layers](#5-architecture-the-layers)
6. [The four state machines](#6-the-four-state-machines)
7. [How you log in without accounts: capability URLs](#7-how-you-log-in-without-accounts-capability-urls)
8. [Codebase map (file by file)](#8-codebase-map-file-by-file)
9. [Follow one charge through the code](#9-follow-one-charge-through-the-code)
10. [Money-handling rules (NON-NEGOTIABLE)](#10-money-handling-rules-non-negotiable)
11. [Testing](#11-testing)
12. [Deployment & configuration](#12-deployment--configuration)
13. [Where to go deeper](#13-where-to-go-deeper)
14. [Glossary](#14-glossary)

---

## 1. What it does (in plain terms)

There are two kinds of people:

- **The planner** (organizer). Creates the event, sets the total cost
  and a goal headcount, shares a link, marks who showed up, and runs
  "settle up" to collect.
- **The attendee.** Taps the planner's link, says Going / Maybe /
  Can't-make-it, and optionally saves a card so they don't have to
  think about paying later.

The happy path, start to finish:

1. Planner creates an event: *"Pickleball Wed, $130 court, goal 15
   people."* The app quotes an **estimate** of $130 ÷ 15 = ~$8.66/person.
2. Planner texts the group a link. People RSVP. Saving a card is
   optional — a saved card is **not** charged yet (see
   [charge-at-close](#4-the-one-idea-to-understand-first-charge-at-close)).
3. After the game, the planner marks who actually played. Say only 12
   showed — the real share is $130 ÷ 12 = ~$10.83.
4. Planner taps **Settle up**. For each attendee who has a card on
   file, the app charges their share automatically. For anyone
   cardless, it produces a **tap-to-pay link** the planner texts them.
5. The planner's roster shows who paid, who owes, and who's on
   auto-pay — so nobody quietly slips through.

The money always routes into the **planner's own Stripe account** —
KnowaPlan is a middleman that computes the split and moves the money;
it never holds the funds.

---

## 2. Project status & scope

This is a **v0** aimed at a single real use case, deliberately kept
small so the money path can be gotten *exactly* right:

| Dimension        | v0 scope                                                       |
| ---------------- | -------------------------------------------------------------- |
| Use case         | Pickleball court splits, one metro area, one known friend group |
| Trust model      | Everyone knows each other — small dollar amounts (~$10–30)     |
| Accounts         | **None.** Identity is a phone number + unguessable links       |
| Payment guarantee | **None** — a saved card can decline, a cardless person can ghost. Accepted risk for a friend group |
| Reminders        | Sent from the planner's *own phone* (pre-filled Messages), no Twilio |
| Frontend         | Server-rendered HTML + form posts; one small JS island for card entry |

Anything bigger — strangers, larger amounts, real accounts, card
*holds* — is explicitly a **later milestone**, and the reasons are
recorded in [`decisions.md`](decisions.md). If a feature request would
push past this scope, that's a "stop and discuss" moment, not a
"just build it" moment.

---

## 3. Quick start

**Prerequisites:** Python 3.12.3, PostgreSQL, and a Stripe test
account.

```bash
# 1. Create a virtualenv and install dependencies
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# 2. Create a local Postgres database
createdb knowaplan

# 3. Create a .env file at the repo root (it is gitignored)
cat > .env <<'EOF'
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
PLANNER_ACCOUNT_ID=acct_...        # the CONNECTED account that RECEIVES money
CREATE_PASSWORD=pick-something     # gates the public "create event" page
# DATABASE_URL=postgresql+asyncpg://localhost:5432/knowaplan  # this is the default
EOF

# 4. Create the database tables
.venv/bin/python -m app.bootstrap

# 5. Run the app
.venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000/ to create an event.

> ⚠️ **`PLANNER_ACCOUNT_ID` is the *connected* account** (the Stripe
> Connect Standard account that *receives* the money), **not** your
> platform account. Stripe rejects a payment whose destination is
> itself. See [`app/config.py`](app/config.py) for the full note.

### Everyday commands

| Task                | Command                                             |
| ------------------- | --------------------------------------------------- |
| Run the app         | `.venv/bin/uvicorn app.main:app --reload`           |
| Create/repair tables | `.venv/bin/python -m app.bootstrap`                |
| Run the tests       | `.venv/bin/pytest`                                  |
| Lint                | `.venv/bin/ruff check .`                            |
| Format              | `.venv/bin/ruff format .`                           |
| Full manual walk-through | See [`demo.md`](demo.md)                       |

> **After changing a model** (`app/models.py`): `bootstrap` only
> *adds* tables, it never *alters* existing ones. So the dev reset is
> drop-and-recreate: `dropdb knowaplan && createdb knowaplan &&
> .venv/bin/python -m app.bootstrap`. Real migrations (Alembic) are a
> live-dogfood concern, deliberately deferred.

---

## 4. The one idea to understand first: charge-at-close

This is **the** mental model. Everything else follows from it.

**We never place a card hold.** When an attendee saves a card at RSVP,
we create a Stripe **SetupIntent** — that saves the card for later but
moves **zero money**. The actual charge happens once, at the end,
after we know who really showed up. That moment is called **close** /
**settlement**.

```
RSVP time                         Close / settlement
─────────                         ──────────────────
Card saved (SetupIntent)   ──▶    Split locks: floor(total ÷ people present)
  • no money moves                Card on file?  → charged automatically
  • just a saved card              No card?       → planner texts a tap-to-pay link
```

Why this matters:

- **The split isn't known until the end.** More people showing up
  lowers everyone's share. A no-show raises it. We can't charge a
  correct number until attendance is final — so we don't charge
  anything until then.
- **A saved card is a convenience, not a guarantee.** It can decline
  when we finally charge it (expired, insufficient funds, an
  off-session block). So **payment is never assumed collected** — the
  roster always shows real, current paid/unpaid state.

> **Historical note for anyone reading old code or `decisions.md`:**
> KnowaPlan *used* to work by placing a worst-case card **hold** at
> RSVP and capturing the actual amount later. That model was retired
> on **2026-07-15** (see the pivot entry in
> [`decisions.md`](decisions.md)). If you see the words `authorized`,
> `voided`, `auth_failed`, "capture," or "hold" in a comment, you're
> looking at history. The live model is charge-at-close.

---

## 5. Architecture: the layers

KnowaPlan is a small, layered FastAPI app. Each layer has one job, and
**the rule that keeps it honest is: only the service layer writes
state, and every state write is checked against a transition table.**

```
                     Browser (a texted link)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  WEB LAYER            app/web.py, app/main.py                 │
│  Thin routes: parse the request → call a service →           │
│  render a Jinja2 template. Routes NEVER write state           │
│  directly. Templates live in app/templates/.                  │
└─────────────────────────────────────────────────────────────┘
                              │  calls
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  SERVICE LAYER                                                │
│    app/events.py      event lifecycle (open, cancel)          │
│    app/rsvps.py       RSVP answers + the /e/ entry path       │
│    app/settlement.py  the record-first money orchestration    │
│    app/payments.py    the Stripe API surface (charge, link…)  │
│  Owns every DB transaction and every state write. Consults    │
│  the state machines before writing.                           │
└─────────────────────────────────────────────────────────────┘
              │  checks                    │  reads/writes
              ▼                            ▼
┌───────────────────────────┐   ┌──────────────────────────────┐
│  STATE MACHINES            │   │  DATA / MODELS               │
│  app/state_machines.py     │   │  app/models.py (ORM rows)    │
│  Pure data: which state    │   │  app/db.py (async engine)    │
│  may follow which. No      │   │  app/config.py (env settings)│
│  behavior.                 │   │  Postgres                    │
└───────────────────────────┘   └──────────────────────────────┘
```

**Two rules you'll see enforced everywhere:**

1. **Routes are thin.** A route parses the form, calls one service
   function, and renders a template. If you find yourself writing a
   `payment.state = "paid"` inside `web.py`, stop — that belongs in a
   service.
2. **State writes go through the table.** Before any service writes
   `state`, it calls `can_transition(MACHINE, current, next)`. An
   illegal move (e.g. `paid → none`) raises an error instead of
   silently corrupting a row. The models store state; they do **not**
   enforce it — the services do, using the tables.

**Tech stack:**

- **Python 3.12** + **FastAPI** + **Pydantic v2**
- **PostgreSQL** via **SQLAlchemy 2.0** (async) + **asyncpg**.
  Everything touching the DB is `async`.
- **Stripe** (Connect Standard, destination charges) for money
- **Jinja2** server-rendered templates + HTML form posts. The only
  browser JavaScript is the Stripe **Payment Element** on the `/r/`
  page, used to save a card.

---

## 6. The four state machines

Almost every row in the database is an instance of a **state machine** —
a thing that can only be in one of a fixed set of states, and can only
move between them along allowed arrows. The arrows are defined once, as
plain Python dictionaries, in
[`app/state_machines.py`](app/state_machines.py), and mirrored in
prose in [`state_machines.md`](state_machines.md). **If the two ever
disagree, the doc wins** and the table is the bug.

### Event — the lifecycle of one gathering

```
draft → open → closed → settled → archived
                 ↓
             cancelled            (from open or closed only)
```

- **draft** — planner is still editing; link not shared yet
- **open** — link shared, accepting RSVPs (a card is optional)
- **closed** — RSVPs locked; the game is happening or just did
- **settled** — attendance marked, charges made / links sent
- **archived** — 72h after settling, read-only
- **cancelled** — called off before settlement; nothing was charged

### RSVP — one person's answer to one event

```
pending → going | maybe | declined      (any answer → any answer while OPEN)
going   → attended | no_show            (planner writes these at settlement)
```

The three answers (going / maybe / declined) are **mutually reachable**
while the event is open — you can change your mind freely. Only the
planner can mark `attended` / `no_show`, and only at settlement.

### Payment — money owed by one person for one event

```
none → paid                (card on file, charged successfully)
none → unpaid              (no card, or the saved card declined)
unpaid → paid              (they paid the tap-to-pay link, or planner confirmed direct payment)
unpaid → abandoned         (planner gave up chasing)
paid → refunded            (reverse a collected charge)
```

`none` is also the *terminal* state for no-shows (nothing owed).
`paid` and `refunded` and `abandoned` are terminal. Note there is **no
`authorized`/`voided`** — those belonged to the retired hold model.

### Attendance — did this person actually show up?

```
unconfirmed → present | absent
```

Resolved once, at settlement. (Attendance and RSVP are two machines
describing the same person-at-an-event, kept on the same
[`Rsvp`](app/models.py) row and always written together.)

---

## 7. How you log in without accounts: capability URLs

There are **no usernames or passwords**. Instead, KnowaPlan uses
**capability URLs**: a link contains a long unguessable token, and
*holding the link IS the permission*. There are four kinds, one token
per purpose, and each route looks up **only its own token column** — so
a link can never be used for the wrong purpose.

| URL                     | Token lives on   | Who holds it | What it lets you do                                |
| ----------------------- | ---------------- | ------------ | -------------------------------------------------- |
| `/e/{event_token}`      | `events`         | The group    | View the event, start an RSVP (name + phone)       |
| `/r/{rsvp_token}`       | `rsvps`          | One attendee | Change *this* event's answer, save a card          |
| `/admin/{admin_token}`  | `events`         | The planner  | Mark attendance, settle up, cancel                 |
| `/me/{attendee_token}`  | `attendees`      | One attendee | **View-only** list of your upcoming events         |

Key design points (all in [`decisions.md`](decisions.md)):

- **The RSVP token is per-event**, not per-person. A leaked `/r/` link
  can only touch one event's answer — not your whole history.
- **The `/me/` page is view-only by construction.** It renders no `/r/`
  links and no buttons, so a leaked bookmark reveals a schedule but
  can't *change* anything.
- **Whoever holds the `/admin/` link is the planner.** That's an
  accepted risk for a friend group; real login is a later milestone.
- Tokens are `secrets.token_urlsafe(16)` (~128 bits), minted as a
  Python-side column default so an insert can't forget to create one.

---

## 8. Codebase map (file by file)

### Application code (`app/`)

| File                    | Responsibility                                                                 |
| ----------------------- | ------------------------------------------------------------------------------ |
| `main.py`               | FastAPI entrypoint. Mounts the router, a friendly 500 handler, `/health`.      |
| `web.py`                | **All HTTP routes.** Thin: parse → service → template. ~22 routes.             |
| `events.py`             | Event lifecycle *before* money is in play: `open_rsvps`, `cancel_event`.       |
| `rsvps.py`              | RSVP answers (`respond`) and the `/e/` entry path (`get_or_create_rsvp`).      |
| `settlement.py`         | **The money orchestrator.** Owns the DB transactions around the Stripe calls: `settle_event`, `mark_attendance`, `close_rsvps`, `retry_dangling`. |
| `payments.py`           | **The Stripe surface.** `create_setup_intent`, `charge_share`, `create_payment_link`, `poll_link_status`, `mark_paid_direct`, `refund_charge` (stub). |
| `state_machines.py`     | The four transition tables + `can_transition()`. Pure data, no behavior.       |
| `models.py`             | SQLAlchemy ORM models: `Planner`, `Attendee`, `Event`, `Rsvp`, `Payment`.      |
| `fees.py`               | Stripe-fee gross-up so the planner nets the exact share (owner-authored; some bodies are stubs). |
| `phone.py`              | `normalize_phone` — canonical 10-digit identity, so autofill vs. typed digits don't create duplicate people. |
| `config.py`             | Settings loaded from env / `.env` (Stripe keys, account id, DB url, create password). |
| `db.py`                 | Async SQLAlchemy engine + per-request session (lazy, so imports need no DB).   |
| `bootstrap.py`          | `python -m app.bootstrap` — `create_all` to build the schema.                  |
| `templates/`            | Jinja2 HTML: `admin.html`, `event.html`, `rsvp.html`, `settle_preview.html`, `settle_report.html`, `me.html`, `paid.html`, and small shared pieces. |

### The canonical docs — read these before any architectural change

These four are the source of truth. `CLAUDE.md` points to them and
says: *"If a change would contradict any of these, stop and ask."*

| Doc                   | What it is                                                              |
| --------------------- | ---------------------------------------------------------------------- |
| [`CLAUDE.md`](CLAUDE.md) | The house rules: stack, money rules, code style, how to work here.  |
| [`decisions.md`](decisions.md) | **Append-only architectural decision log.** Every "why" lives here, newest at the bottom. This is the most important doc in the repo. |
| [`state_machines.md`](state_machines.md) | The Event / RSVP / Payment / Attendance contracts in prose. |
| [`scenarios.md`](scenarios.md) | User-facing edge-case behavior (walk-ins, cost changes, no-shows, declines). |

### Operational & reference docs

| File / dir            | What it is                                                             |
| --------------------- | ---------------------------------------------------------------------- |
| [`demo.md`](demo.md)  | Step-by-step test-mode walk of the whole slice, solo, with test cards. |
| [`runbook.md`](runbook.md) | The planner's day-of crib sheet for running a real event.         |
| `skeleton_01_auth.py` / `skeleton_02_payment.py` | Early "walking skeleton" scripts that proved Stripe auth and the payment call in isolation. Reference only. `skeleton_02` predates the hold→charge pivot — see its header note. |
| `Dockerfile`          | Deploy image (Railway). The `--proxy-headers` flags are load-bearing (see below). |
| `MISSION.md`, `NOTES.md`, `RESOURCES.md`, `lessons/`, `learning-records/`, `reference/` | Learning material — this repo doubles as a study project for its owner. Not needed to run or change the app, but `RESOURCES.md` has verified Stripe doc links and `reference/codebase-map.html` is a visual tour. |

---

## 9. Follow one charge through the code

The single most useful thing to trace is: **what happens when the
planner taps "Settle up."** This is the path `MISSION.md` calls "one
tap to one charge." Here it is end to end.

1. **Route** — `POST /admin/{token}/settle` in
   [`app/web.py`](app/web.py) (`settle_route`). It validates `mode`
   (`actual` or `cap` — capping and absorbing the gap is an *active*
   choice, never a default), looks up the event and planner, and calls
   the service.

2. **Orchestration** — `settle_event()` in
   [`app/settlement.py`](app/settlement.py):
   - If the event is still `open`, it closes RSVPs first.
   - It gathers every RSVP + attendee, and decides who counts as a
     **participant** (marked present, or defaulted per the planner's
     `settle_default`).
   - It computes the split: `share = total_cost_cents // divisor`
     (integer floor — see the split rule below).
   - It refuses **before touching money** if the per-person charge
     would be under Stripe's **50¢ minimum**.

3. **Record-first, per attendee** — for each person who should be
   charged (and who is *not* the planner):
   - **First DB commit:** write a `Payment` row stamped with
     `charge_requested_at` and `charge_requested_cents` — the *intent*
     to charge, and *how much* — in one transaction, **before** any
     Stripe call.
   - **Then the Stripe call**, via `_collect()`:
     - Card on file → `charge_share()` in
       [`app/payments.py`](app/payments.py) creates an off-session
       `PaymentIntent`. Success → `Payment.state = paid`. A decline →
       `unpaid`, and a tap-to-pay link is minted.
     - No card → the row goes `unpaid` and `create_payment_link()`
       mints a Checkout link the planner texts.
   - **Then the terminal state is written.**

4. **Report** — `settle_event` returns a `SettlementReport` (the true
   share, what was actually charged, any absorbed shortfall, and a
   per-attendee outcome list). The route renders `settle_report.html`.

**Why the odd ordering?** Because Stripe is not part of our database
transaction, and a crash can happen *between* our write and Stripe's
response. If we called Stripe first and crashed, money could move with
no record of it — discovered only by an angry text. So we **write our
intent first**. If we crash after stamping but before Stripe answers,
the row is a **dangling charge** (stamp set, `state` still `none`) —
findable by a query, surfaced on the admin page, and safely retried
with the **same idempotency key**, so Stripe replays the original
outcome instead of double-charging.

> **The principle, in one line:** *the database must always know at
> least as much as Stripe.*

---

## 10. Money-handling rules (NON-NEGOTIABLE)

These come straight from [`CLAUDE.md`](CLAUDE.md). Internalize them
before touching money code:

- **Integer cents, never float.** All amounts are `int` cents. There
  is exactly one place a number gets a `$` (a template filter). Form
  input is parsed with `Decimal`, never `float`.
- **No card holds in v0.** Charge the actual share at close. A saved
  card is a SetupIntent, not an authorization — no money moves until
  close.
- **Payment is NOT guaranteed.** A saved card can decline; a cardless
  attendee can ghost. Always surface unpaid balances on the roster;
  **never assume collected.**
- **Actual > estimate → charge actual by default.** If fewer than the
  goal show up, the real share is higher than quoted. The planner may
  *choose* to absorb the gap ("cap"), but **silence charges the actual
  share** — absorbing is an active generosity choice.
- **Every charge uses an idempotency key** derived from
  `(payment.id, operation)` — e.g. `"{payment.id}:charge"`. A retry
  after a blip reuses the key (can't double-charge); a genuinely new
  attempt is a new row with a fresh key.
- **Record-first.** Intent (timestamp **and** amount) is written in
  the same DB transaction as the attendance change, *before* the
  Stripe call. Terminal state is written *after*.
- **Refund = reversing an already-collected charge, only.**

### The split rule (why floor, not ceil)

Everyone pays `floor(total_cost_cents / headcount)`, and the planner
absorbs the leftover cents — at most `headcount − 1` cents per event.
Nobody is ever charged a cent more than anyone else. (Distributing the
odd cents would be "fairer" by pennies but invites *"why did I pay more
than him?"* — social cost, no monetary upside.)

### The money guard (enforced, not advisory)

A `PreToolUse` hook — [`.claude/hooks/money_guard.py`](.claude/hooks/money_guard.py) —
**denies any `.py` edit that calls the Stripe Refund API without the
marker `refund-guard: captured-only`**. A refund must only ever reverse
an already-collected charge (`Payment.state == "paid"`). The guard
fails closed and its behavior is pinned by
`tests/test_money_guard.py`. This is a machine enforcing a money
invariant — it is not a style preference.

---

## 11. Testing

Run everything with `.venv/bin/pytest`. There are ~210 tests across 18
test files (plus shared fixtures in `conftest.py`), and they are
**fully hermetic** — they never touch a real database or the live
Stripe API.

Two safety layers (both in [`tests/conftest.py`](tests/conftest.py)):

1. **Credentials are blanked** for the whole test process (an autouse
   fixture), so nothing can accidentally reach real Stripe.
2. **`mock_stripe`** — a `MagicMock` stand-in injected into
   `app.payments`. Tests assert against the *recorded calls*. (Real
   exception classes are imported from the SDK so `except` clauses
   still work — importing Stripe makes no network call.)

The database in tests is **in-memory SQLite** (`aiosqlite`) via the
`db_session` fixture. That gives **real async commits** — so the
record-first ordering is genuinely exercised — while staying hermetic.
Full Postgres fidelity arrives with live dogfood.

What the test files cover, at a glance:

| Test file                    | Focus                                              |
| ---------------------------- | -------------------------------------------------- |
| `test_state_machines.py`     | The transition tables match `state_machines.md`    |
| `test_payments.py`           | The Stripe surface: charge, link, poll, idempotency |
| `test_settlement.py`         | `settle_event` splitting, record-first, dangling   |
| `test_settle_web.py`         | Settlement through the HTTP routes                 |
| `test_rsvps.py` / `test_rsvp_pages.py` | RSVP transitions and the `/e/`, `/r/` pages |
| `test_web.py` / `test_app.py` | Routing, rendering, schema shape                  |
| `test_fees.py`               | Stripe-fee gross-up math                            |
| `test_phone.py`              | Phone canonicalization                             |
| `test_money_guard.py`        | The refund guard hook                              |
| `test_pay_direct.py`, `test_admin_actions.py`, `test_me_page.py`, `test_courtside_polish.py`, `test_attendee_polish.py`, `test_tokens.py`, `test_submit_guard.py` | Direct-payment claims, admin actions, the /me page, UX polish, tokens |

---

## 12. Deployment & configuration

### Environment variables

Loaded by [`app/config.py`](app/config.py) from real env vars or a
gitignored `.env` (real env vars win).

| Variable                  | Purpose                                                                 |
| ------------------------- | ----------------------------------------------------------------------- |
| `DATABASE_URL`            | Postgres URL. A driverless `postgres://` / `postgresql://` (as managed hosts hand out) is auto-rewritten to `postgresql+asyncpg://`. |
| `STRIPE_SECRET_KEY`       | Server-side Stripe key. Blank in tests.                                 |
| `STRIPE_PUBLISHABLE_KEY`  | Browser key for the `/r/` Payment Element. Not a secret, still env-set. |
| `PLANNER_ACCOUNT_ID`      | The **connected** account that *receives* money. Not the platform account. |
| `CREATE_PASSWORD`         | Gates the public "create event" page. **Unset = event creation refused** (fail closed). |

### Docker / Railway

The [`Dockerfile`](Dockerfile) builds a Python 3.12 image and runs
uvicorn. The `--proxy-headers --forwarded-allow-ips '*'` flags are
**load-bearing, not cosmetic**: behind a proxy they make
`request.base_url` honor `X-Forwarded-Proto/Host`, so the share links
the app prints read `https://<public-domain>/e/...` instead of an
internal `http://` hostname. Without them, every link the planner texts
is wrong.

### No webhooks in v0

Every money call returns its outcome synchronously in the same request,
and 3DS is deferred — so nothing arrives asynchronously and there is no
webhook endpoint. Instead, when a cardless attendee pays a tap-to-pay
link, the app **polls that Checkout Session's status on roster load** to
move the row `unpaid → paid`. Disputes and bank reversals (which only
arrive by webhook) are a live-dogfood concern.

---

## 13. Where to go deeper

- **To understand *why* something is the way it is:** read
  [`decisions.md`](decisions.md), newest entries at the bottom. The
  2026-07-15 "charge-at-close" pivot is the hinge of the whole design.
- **To understand a state contract:** read
  [`state_machines.md`](state_machines.md) alongside
  [`app/state_machines.py`](app/state_machines.py).
- **To understand a user-facing edge case** (walk-ins, cost changes,
  declines, disputes): read [`scenarios.md`](scenarios.md).
- **To run the whole thing by hand:** follow [`demo.md`](demo.md).
- **For a visual tour:** open `reference/codebase-map.html` and
  `reference/payment-row.html` in a browser.

---

## 14. Glossary

| Term                   | Meaning                                                                 |
| ---------------------- | ----------------------------------------------------------------------- |
| **Planner**            | The organizer who creates the event and collects money. Money routes into *their* Stripe account. |
| **Attendee**           | Someone invited to the event. Identified by phone number.               |
| **Close / settlement** | The moment attendance is final and the app computes and charges each share. |
| **Charge-at-close**    | The core money model: no holds; charge the real share once, at the end. |
| **SetupIntent**        | A Stripe object that *saves* a card for later. Moves no money.           |
| **PaymentIntent**      | A Stripe object that *charges* a card. Created at close.                 |
| **Tap-to-pay link**    | A Stripe Checkout link the planner texts to a cardless (or declined) attendee. |
| **Capability URL**     | A link whose unguessable token *is* the permission — no login needed.   |
| **Record-first**       | Write the intent-to-charge to the DB *before* calling Stripe, so a crash is recoverable. |
| **Dangling charge**    | A `Payment` row with the intent stamp set but `state` still `none` — a charge whose Stripe outcome is unknown. Safely retried with the same idempotency key. |
| **Idempotency key**    | A string that tells Stripe "if you've seen this exact request, replay the old result" — prevents double-charging on retries. |
| **Connected account**  | The planner's Stripe Connect account, which *receives* the group's money. |
| **Estimate**           | `total ÷ goal attendance`, quoted at RSVP. Not a hold — display and expectation only. |
| **Cap-and-absorb**     | The planner's option at settlement to charge only the quoted estimate and personally eat the difference. |
| **Goal attendance**    | The planner's expected headcount, set at creation. Sizes the estimate.  |

---

*KnowaPlan custodies real money for real friends. When in doubt,
choose correctness over speed, and check your change against
[`decisions.md`](decisions.md) and the
[money rules](#10-money-handling-rules-non-negotiable).*
