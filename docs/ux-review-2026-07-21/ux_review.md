# KnowaPlan phone-UX review — 2026-07-21

A feel-focused review of every screen before the first real-money
event (2026-07-29). Both personas walked end to end in Chromium at
390x844 (iPhone-ish), 53 screens staged and screenshotted, plus an
objective probe per page (horizontal overflow + tap-target sizes).
This is a REVIEW: nothing in the app was changed. Every fix below is
a proposal; per CLAUDE.md align-before-acting, none lands without
owner approval, and any fix that touches pinned copy names the test
it would update.

## How it was staged (and what to discount)

- SQLite + fake Stripe keys; every Stripe call fails as a contained
  error. That is exactly what let the failure screens be staged:
  settle ran to completion with per-attendee outcomes (`dangling`,
  `unpaid`), the claim/confirm-direct-pay loop ran for real, and one
  attendee got a fake `pm_` id seeded in the throwaway DB to reach
  the record-first "charge requested — unconfirmed" state.
- Discount these capture artifacts: Linux fallback fonts (a real
  iPhone renders SF Pro Rounded — softer, friendlier than these
  shots); a few buttons show a pink "hover" fill (headless mouse
  parked where it last clicked); full-page shots were captured with
  the background gradient un-fixed (identical pixels at the top of
  the page, and it dodged a headless renderer stall).
- Shots live in `shots/` (numbered; `-fold` = the first 844px, what
  a phone shows before scrolling). Probe data: `probes.json`.

## TL;DR

The bones are genuinely good: the money story ("Nothing is charged
now… only if you play") is told at the right moments in the right
words, the settle preview is the best screen in the app, and nothing
horizontally scrolls at 390px. The gaps are concentrated in four
places: (1) the admin page pushes "Settle up" as the primary action
all week and lets a stray attendance tap silently close RSVPs; (2)
a handful of raw internals leak to humans — `no_card`, "dangling",
"decisions.md 2026-07-13", "you're didn't play"; (3) the payer whose
card charge is mid-flight sees nothing about money at all; (4) the
cancel-confirm page tells a planner "Nothing has been charged" on an
event where money already moved. All four are template/copy-level
fixes; none touches the state machines or payment mechanics.

---

## Feels good — keep (and defend)

- **K1 · /e/ open** (10): money reassurance FIRST, then a two-field
  form, one obvious CTA, and lost-link recovery in the footer
  ("Enter the same phone to get back"). The app at its best.
  Copy pinned by tests/test_rsvp_pages.py — keep pinned.
- **K2 · Card pitch + card-on-file** (13, 15): "You're only charged
  if you play — marked absent means nothing is charged." answers the
  exact fear that makes people refuse to save a card. Pinned by
  tests/test_courtside_polish.py.
- **K3 · Settle preview** (21, 27, 49): the money-trust centerpiece.
  Divisor explained in one breath ("including you — you count in the
  divisor and are never charged"), warnings are specific and tell
  the planner what to do about them, and the choice buttons carry
  their own math ("Cap at the estimate ($20.00 each) — I absorb
  $30.00"). Do not simplify this screen away.
- **K4 · Direct-pay loop** (32–37): Venmo/Zelle handles shown to the
  person who owes, claim flag ("says they paid — venmo"), planner
  confirm/deny side by side, "paid ($20.00 direct)" on the roster,
  green "Noah marked you paid ✓ (zelle)" for the attendee. The
  never-assume-collected rule made visible and warm.
- **K5 · /paid + 404** (04, 05): "You're square" 🎉 and "This link
  doesn't point anywhere" + how to recover. Friendly, blame-free.
- **K6 · The system itself**: warm palette on every screen, pill
  buttons, ZERO horizontal overflow on all 53 pages, 16px inputs (no
  iOS focus-zoom), `type=tel inputmode=tel autocomplete=tel`
  everywhere a phone is asked, double-submit guard on every form.
- **K7 · Stale-link states** (08, 44, 52): draft says "check back
  once Noah shares it"; cancelled says "Nothing was charged";
  settled /e/ says "Talk to Noah if something's off."
- **K8 · Phone validation** (03, 11): "use 10 digits, like
  6195550123" with the form kept filled. Concrete, fixable, kind.

---

## Feels off — fix

### High impact

- **F1 · admin, open state (09, 20): the primary CTA is wrong for
  the moment.** All week before the game, the filled coral button is
  "Settle up" — the one action that ends RSVPs and moves money — while
  the actual next action (text the share link) is an outline Copy
  button two sections down. Fix, state-aware: while the event is
  open and nobody is marked, render the Share-link section directly
  under the meta line with **Copy as the primary (filled) button**,
  and "Settle up" as an outline button below; flip prominence once
  RSVPs close or marking starts. No pinned copy touched.
- **F2 · admin roster, open state (20 → 22): a stray attendance tap
  silently closes RSVPs.** `present`/`absent` buttons are live on
  every going row from day one, and the FIRST tap auto-closes the
  event with no announcement — the badge just quietly reads
  "closed" (22). Courtside fat-thumb risk, days early. Fix at the
  template level (the state machine's open→closed-on-first-mark
  transition is untouched): while the event is open, replace the
  per-row buttons with one explicit step —
  "**Start attendance — this closes RSVPs**" — which reveals the
  buttons; and after any close, show one line under the title:
  "RSVPs are closed — new people can't join." No test pins this.
- **F3 · cancel confirm on a charged/settled event (47): the page
  lies.** GET /admin/{t}/cancel has no state guard, so an event with
  a confirmed direct payment, an unconfirmed card charge, and an
  unpaid balance still shows "Nothing has been charged" over a red
  "Yes — cancel the event" button that can only land on the 400
  (48). Fix: guard the GET the same way `cancel_event` guards the
  POST — if any Payment row is non-pristine, render the explanation
  instead of the confirm ("Money has already moved for this event —
  cancelling is locked. Finish settling instead: retry the flagged
  row, re-send links."). Keep the current confirm + copy for the
  pristine case — tests/test_admin_actions.py::test_cancel_confirm_page
  pins "Nothing has been charged" there, and it stays true there.
- **F4 · 502 error page (38): internal citation shown to a worried
  planner.** "…retrying again is safe (same idempotency key,
  decisions.md 2026-07-13)." — idempotency keys and doc references
  are our language, not Noah's, and "Can't do that" is the wrong
  heading for an outage (nothing was refused). Fix — heading
  "Couldn't reach Stripe", body: "Stripe didn't answer, so this
  charge is unconfirmed. Nothing can be double-billed — a retry
  reuses the same charge. The row stays flagged on the roster; try
  again in a minute." Not test-pinned (verify at implementation).
- **F5 · /r/ while a charge is unconfirmed (31): the payer sees no
  money info at all.** Dana played, has a card on file, her charge
  is mid-flight (record-first stamp set, state still `none`) — and
  her page shows nothing about money, while every other participant
  sees their line. If the retry lands she gets charged $20 with no
  prior trace on her own page. Fix: when settled + card on file +
  charge requested but unconfirmed, render: "Your share is $20.00 —
  it's charging to your saved card. If it doesn't go through, Noah
  will text you a payment link." New conditional; no pinned copy.
- **F6 · every screen: 24-hour time.** "Starts Tue Jul 28, 18:00" —
  a US friend group reads 6:00 PM. One strftime in each template
  (`web.py` passes the datetime; templates format it). Fix:
  "%a %b %-d · %-I:%M %p" → "Tue Jul 28 · 6:00 PM". No test pins a
  time string.

### Medium impact

- **F7 · roster (30, 36): enum tokens with underscores reach the
  screen.** "unpaid no_card" reads like debug output; the `no_show`
  badge carries an underscore. The raw-enums-for-the-planner choice
  (admin.html comment) is about precision — keep the words, fix the
  formatting: a tiny display map (`no_card` → "no card",
  `card_declined` → "card declined", `no_show` → "no-show"), joined
  with an em-dash: "unpaid — no card". Collision: the design
  comment in admin.html (refine it, don't delete it); check whether
  any test greps `no_card` in HTML at implementation time.
- **F8 · settle report vs roster (29 vs 30): one state, two names.**
  The report says "dangling"; the roster calls the same row "charge
  requested — unconfirmed" (the good name). Use the roster's phrase
  on the report too, plus one reassurance clause: "charge requested —
  unconfirmed. Stripe didn't answer; Retry is safe (it reuses the
  same charge)." Collision: tests/test_settle_web.py::
  test_stripe_error_surfaces_as_dangling_with_retry pins "dangling"
  — update the assertion with the copy.
- **F9 · roster, settled (30): no money summary.** decisions.md
  2026-07-15 promises "exposure visible"; today the planner counts
  unpaid rows by scrolling. Fix: one line under "Roster" once
  settled: "Collected $20.00 of $60.00 · 1 unconfirmed · 1 unpaid."
- **F10 · roster, closed/settled/cancelled (30, 36, 51): the dead
  share link still owns the top of the page.** After open, collapse
  the Share-link section to a one-line muted link (or drop it);
  pairs with F1's reordering.
- **F11 · /r/ status sentence (12, 42): enum-in-sentence grammar.**
  "you're **not answered yet**", "you're **didn't play**". Badges
  are fine; sentences need their own templates: "you haven't
  answered yet", "you played", "you're down as a no-show", "you're
  not going". Collision: tests/test_attendee_polish.py pins the
  current strings ("not answered yet", "didn&#39;t play") — update
  those assertions with the copy; the STATE_LABELS badge map keeps
  its short labels for /me/ and roster badges.
- **F12 · /r/ settled for non-participants (41, 42, 43): missing
  "you weren't charged."** The no-show, the stale maybe, and the
  declined friend all get "This event is settled up" and silence
  about money. One added line each: "You weren't charged." (For the
  playing planner: "You count in the split but are never charged —
  your share is just court cost you don't recoup.")
- **F13 · error pages (07, 23, 38, 40, 48): right words, dead ends.**
  "Can't do that" wears wrong on outages (F4) and every error page's
  only exit is a 19px "← Go back" history link. Where the route knows
  the token, add a real way home: "Back to your RSVP page" (/r/) or
  "Back to the roster" (/admin/). Also fix the enum-prose message
  "can't settle an event that is draft" → "This event isn't open
  yet — open RSVPs first."
- **F14 · create form (01): four small frictions.** (a) The money
  reassurance ("Nothing is charged until after the game.") sits BELOW
  the submit button — move it to a muted line right under the H1.
  (b) "Goal attendance" is jargon — label it "How many do you
  expect?" with helper "sets the estimate everyone sees (total ÷
  this)". (c) The settle-default select truncates at 390px
  ("Assume everyone going attended (cha…") — shorten options:
  "Charge everyone still marked going" / "Charge nobody I haven't
  marked". (d) "Create password" reads like "make up a password" —
  "App password" + helper "the CREATE_PASSWORD you set in .env".
  Collision: none pinned (test_web checks field names, not labels).
- **F15 · admin (06): nobody tells the planner this URL is the key.**
  The attendee pages say "Bookmark it" twice; the admin page — the
  one link that controls money and cannot be recovered — says
  nothing. Fix, one muted line under the title while draft/open:
  "This page is your admin key — bookmark it. Anyone with this link
  controls the event."
- **F16 · /r/ card on file (15): no way to change your mind.** Once
  saved, the card can't be replaced or removed — a nervous friend's
  only path is texting the planner, who also has no tool. Cheapest
  honest fix: "Use a different card" button that re-opens the island
  (a new SetupIntent overwrites the payment method; no money moves —
  record_saved_card already overwrites). Alternative if that's
  deferred: an honest line "Want the card off? Text Noah."
- **F17 · tap targets, global (probes.json): everything is 38–41px;
  the escape hatches are 16–19px.** Buttons sit just under the 44px
  bar (fine-ish given spacing), but the text links that are the ONLY
  exit from pages — "⌂ Your events" (16px), "← Go back" (19px),
  "Back to the roster" (19px) — are genuinely small thumb targets.
  Fix in base.html: button padding .55rem→.65rem (≈44–46px), and
  give .home/.muted nav links `display:inline-block; padding:.6rem
  .2rem` so the hit area clears ~44px without visual change.
- **F18 · settle preview (21, 27): says how much, not how.** Add one
  muted line so the planner knows what happens on tap: "1 saved card
  charges automatically · 2 get a payment link · 1 maybe won't be
  charged."

### Low impact

- **F19 · roster, open (20):** every row reads "no card ·
  unconfirmed" + an empty "—" payment slot — three bits of noise per
  card before the game. Hide the attendance word while open, and
  drop the "—" placeholder until a Payment row exists.
- **F20 · roster, open (20): no headcount line.** "4 going · 1 maybe
  · goal 6" under the Roster heading answers the planner's #1
  question without counting cards. (Arguably medium; it's one line.)
- **F21 · card island failure (14):** good copy, add the recovery
  clause: "card setup is unavailable right now — you can skip it:
  you'll get a tap-to-pay link after the game instead."
- **F22 · /me/ after settle (45):** the just-played event vanishes
  entirely ("No upcoming events yet") — continuity feels off for
  Dana whose charge is still unconfirmed. Deliberate (2026-07-21:
  open+closed only, no money surface on /me/). If ever revisited: a
  link-less ghost row "Tuesday Pickleball — settled up" keeps
  continuity without growing a money surface. Named collision:
  decisions.md 2026-07-21.
- **F23 · claim rejected (35):** the attendee isn't told; the claim
  form silently returns on their page. Fine for a friend group
  (they'll text); note only.
- **F24 · _dollars (web.py):** no thousands separator — "$1234.56".
  Irrelevant at $8–30; safe to leave. If fixed, only amounts ≥$1,000
  change, so no pinned $XX.XX test strings are touched.
- **F25 · settle report empty-ish header (29):** consider adding the
  collected/outstanding totals here too once F9 exists (same line).

---

## Journey verdicts in one line each

- Planner create → open: warm and fast; fix the footnote placement
  (F14) and the key-bookmark line (F15).
- Planner mid-week: roster is calm and readable; fix CTA hierarchy
  (F1) and the attendance booby trap (F2).
- Attendee RSVP → card: the best-written flow in the app (K1, K2);
  add the island-failure recovery clause (F21).
- Settle: preview excellent (K3); report needs the state renamed
  (F8) and the per-method line (F18).
- Post-game money chase: mechanics all there and honest (K4); fix
  the limbo-payer silence (F5), summary line (F9), and enum
  formatting (F7).
- Errors: friendliest 404 in class (K5); outage pages need human
  vocabulary and a road home (F4, F13).

## Probe appendix (objective, all 53 pages)

- Horizontal overflow: **none** — no page scrolls sideways at 390px.
- Tap targets under 44px (worst first): "⌂ Your events" /
  "Your events" links 16px tall (21 pages); "← Go back" 19px (6
  error pages); "Back to the roster" 19px (7 pages); all pill
  buttons 38–41px (every page); inputs 39–41px. Full per-page data
  in `probes.json`.

## Reviewed from code only (not screenshottable with fake keys)

- `link_result.html` (tap-to-pay link + iOS `sms:` prefill): copy
  reads right ("shown once — re-mint from the roster if you lose
  it"); same F17 link-size note applies to its footer.
- The settle `data-wait` freeze message ("Settling 4 people — keep
  this page open until the report loads.") — settle completed too
  fast under fake keys to observe; pinned by test_submit_guard.
- mark-paid 409 ("already paid the app link") and a real paid-link
  poll flip — need live Stripe; copy consistent with siblings.
- `sms:` links never clicked (would hang headless); href shape
  pinned by test_courtside_polish.

## Proposed decisions.md drafts (only if the owner adopts them)

1. **Screen vocabulary rule.** Enum values never reach a screen
   raw: planner surfaces keep the state WORDS but format them
   (underscores become spaces/hyphens, reasons join with an
   em-dash); attendee surfaces use per-state sentence copy, badges
   use the short label map. Refines (does not retire) the
   raw-enums-on-purpose comment in admin.html.
2. **State-aware admin hierarchy.** The admin page's filled-primary
   button follows the event's moment: open+unmarked = share/Copy;
   closed-or-marking = Settle up; settled = none (roster is the
   surface). Cancel never renders filled.

## Suggested order of attack (if adopting)

1. F3 (false "nothing charged" page) + F4 (decisions.md leak) — the
   two trust wounds; template + one route guard; ~an hour.
2. F2 + F1 (attendance trap + CTA hierarchy) — courtside safety.
3. F5 + F12 (money lines on /r/ for limbo payer + non-participants).
4. F6 (12-hour time), F11 (sentence grammar, with its two test
   updates), F7/F8 (enum formatting + one name for the unconfirmed
   state, with its one test update).
5. F9/F10/F14–F21 as batched polish.

Everything above is a proposal. Per align-before-acting, each item
(or batch) gets a walkthrough with exact body drafts and the test
list before any file changes.
