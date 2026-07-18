# KnowaPlan money path — Resources

Every URL below was fetched and verified (2026-07-16). Quoted figures
are literal. Where Stripe's own docs disagree with each other, that is
noted — do not paper over it.

> Trick worth knowing: Stripe serves a raw Markdown twin of every doc
> page at `<url>.md`. Fetch that instead of the HTML when you want to
> grep for an exact sentence.

## Knowledge — Stripe (primary)

- [How Payment Intents and Setup Intents work](https://docs.stripe.com/payments/paymentintents/lifecycle)
  The canonical lifecycle/status page. Use for: what each status means,
  and the fact a failed attempt returns the PI to
  `requires_payment_method` rather than destroying it. *(Note:
  `/payments/intents` 301s here. The `#intent-statuses` anchor the API
  ref links to does not exist — link the bare page.)*
- [The PaymentIntent object](https://docs.stripe.com/api/payment_intents/object)
  Authoritative status enum: `requires_payment_method`,
  `requires_confirmation`, `requires_action`, `processing`,
  `requires_capture`, `canceled`, `succeeded`.
- [The Setup Intents API](https://docs.stripe.com/payments/setup-intents)
  Use for: why `usage="off_session"` makes 3DS run *at save time* —
  "although it creates initial friction in the setup flow, setting
  `usage` to `off_session` can reduce customer intervention in later
  off-session payments." Also: `usage` defaults to `off_session`.
- [Set up future card payments](https://docs.stripe.com/payments/save-and-reuse-cards-only?platform=web&payment-ui=direct-api)
  The off-session charge mechanics. **The query string matters** — the
  bare URL is a nav stub. Use for: the 402 + `requires_payment_method`
  decline path, and `last_payment_error.decline_code`.
- [Create a Checkout Session](https://docs.stripe.com/api/checkout/sessions/create)
  Settles the `success_url` question: **"required conditionally"** —
  disallowed only for `ui_mode` embedded/elements, therefore required
  for our hosted page. Also the only page stating session expiry: "from
  30 minutes to 24 hours… By default, this value is 24 hours."
- [The Checkout Session object](https://docs.stripe.com/api/checkout/sessions/object)
  Use for: `status` vs `payment_status` — **not interchangeable**.
  `status: complete` = "Payment processing may still be in progress."
  Only `payment_status: paid` = "The payment funds are available in
  your account." Our code gets this right; keep it that way.
- [Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
  and [Advanced error handling](https://docs.stripe.com/error-low-level)
  Use for: the replay contract. **The two pages disagree** — the first
  says keys may be pruned once "at least 24 hours old", the second says
  they "expire out of the system after 24 hours." Safe claim: *retry
  within 24h and Stripe replays; past 24h, do not rely on it.*
- [Errors](https://docs.stripe.com/api/errors)
  The real name is the type `idempotency_error`, not a class called
  `IdempotencyError`. Fires on a key reused with a different "API
  endpoint and parameters."
- [Create destination charges](https://docs.stripe.com/connect/destination-charges)
  Use for: `on_behalf_of` (settlement merchant) vs
  `transfer_data.destination` (where funds land). **Contains our live
  blocker**: `on_behalf_of` "is supported only for connected accounts
  with a payments capability such as `card_payments`."
- [API upgrades](https://docs.stripe.com/upgrades)
  Use for: object id length. Stripe calls changing id length/format
  *backward-compatible* (shippable without a version bump) and says
  "Make sure that your integration can handle Stripe-generated object
  IDs, which can contain up to 255 characters."
- [Error codes](https://docs.stripe.com/error-codes)
  Use for: reading `state_reason` on an unpaid row.

## Knowledge — Connect, fees, and who pays (verified 2026-07-16)

- [Charge types](https://docs.stripe.com/connect/charges)
  **The single most important page for this codebase.** Destination
  charges: "You create a charge on your platform, so the payment appears
  in your platform's balance… **Stripe debits fees from your platform's
  balance.**" Also: "Refunds and chargebacks reduce your platform's
  balance," and the dispute rule — platform is debited "with or without
  `on_behalf_of`."
- [Migrate to controller properties](https://docs.stripe.com/connect/migrate-to-controller-properties)
  Explains `type: "none"`. Our connected account matches the documented
  **Express**-with-controller-properties response byte for byte. Also
  gives the real Standard mapping: `losses.payments: stripe`,
  `fees.payer: account`, `stripe_dashboard.type: full`.
- [Fee behavior on connected accounts](https://docs.stripe.com/connect/direct-charges-fee-payer-behavior)
  **Read the caveat, not the table.** The table is scoped to *direct*
  charges. The caveat is what governs us: "Any activity occurring at the
  platform account level is billed to your platform **regardless of the
  entity responsible for fee collection**… Stripe charges the platform
  directly for destination charges."
  → `controller.fees.payer` is **not** a lever for us. Do not "fix" it.
- [Account object](https://docs.stripe.com/api/accounts/object)
  `controller.losses.payments` is about **negative balances**, not
  disputes. `type: "none"` = "created with controller attributes that
  don't map to a type of `standard`, `express`, or `custom`."
- [Connected account types](https://docs.stripe.com/connect/accounts)
  Dispute liability by charge type: "Standard: Connected account for
  direct charges, **Platform for destination charges**."
- [Create a PaymentIntent](https://docs.stripe.com/api/payment_intents/create)
  `transfer_data.amount`: "**if no amount is set, the full amount is
  transferred**." This one omitted parameter is the whole fee story.
- [stripe.com/pricing](https://stripe.com/pricing) — **note the domain.**
  docs.stripe.com does *not* publish Stripe's own rate; every docs page
  defers here. US domestic card: 2.9% + 30¢. Confirmed empirically
  against our own account ($40 → $1.46, $32 → $1.23, both exact).

## Knowledge — the stack (verified 2026-07-17)

- [FastAPI: Bigger Applications — Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
  The documented pattern main.py + web.py implement: routes on an
  `APIRouter`, mounted via `app.include_router()` — "it will include
  all the routes from that router as part of it." Use for: the
  entrypoint's shape, and what the pattern offers (prefixes, shared
  dependencies) that this codebase doesn't use yet.
- [FastAPI: Dependencies with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)
  db.py's `get_session` is this page verbatim: "use `yield` instead
  of `return`," code before the yield runs before the handler, "the
  code following the `yield` statement is executed after the
  response." The page's own example is a database session.
- [SQLAlchemy 2.0: Asyncio extension](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
  `create_async_engine` / `async_sessionmaker` / `AsyncSession`, and
  the reason db.py sets `expire_on_commit=False`: by default commit
  expires attributes, and touching them afterward triggers implicit
  IO — forbidden in asyncio. Use for: the transactions lesson and
  any session-lifecycle question.

## Wisdom (Communities)

Not yet proposed — the mission's deadline is 13 days out and the
questions so far are answerable from primary sources. Revisit after
7/29, when the questions become judgement calls ("should I reintroduce
holds?") rather than fact lookups.

## Gaps

- **Commit semantics for the record-first lesson.** The SQLAlchemy
  asyncio page (above) covers sessions and expire_on_commit; still
  missing a primary source on what a COMMIT *guarantees*
  (atomicity/durability at the database) pitched right — likely the
  PostgreSQL docs' transactions tutorial. Verify before writing the
  transactions lesson.
- ~~**Stripe Connect Standard onboarding / `card_payments` capability**~~
  **CLOSED 2026-07-16.** Checked the real account: `card_payments:
  active`, `charges_enabled: true`, `currently_due: []`. Not a blocker.
  The account is Express-equivalent, not Standard — see NOTES.md.
- **Dispute liability vs `controller.losses.payments`** — *unverified,
  do not assert either way.* No Stripe page connects them. Destination
  charges debit the platform as a property of the **charge type**;
  `losses.payments` is documented only against **negative balances**.
  Two separate mechanisms with no documented interaction.
- **"Payment method must live on the platform for destination charges"**
  — asserted in `app/models.py` and `app/payments.py`, but **no Stripe
  page states it as a rule.** It is only *entailed* by "the charge is
  created on your platform's account." Treat as a well-founded inference
  until a citation is found; do not teach it as quoted doctrine.
