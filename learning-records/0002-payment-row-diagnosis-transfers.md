# Payment row diagnosis transfers to unseen scenarios

After Lesson 1, Noah correctly diagnosed a live scenario the lesson
never showed: Dave standing at the court, `state=unpaid`,
`state_reason=insufficient_funds`, a `pi_…` id present, saying "just run
my card again." He chose **text him the link** over three distractors.

**Why this is evidence and not luck:** the strong distractor was "press
Retry charge." The roster *has* that button, the row *has* a
record-first stamp on it, and it reads as retryable. Rejecting it
requires holding two things at once — that Retry is only for
`state=none` (`retry_dangling` raises "not a dangling charge";
`admin.html` won't even render the button), and that `unpaid` recovers
via the link only. He also implicitly rejected "recharge his saved
card," which is the invariant from decisions.md 2026-07-16 that
`charge_share` fires from `none` only.

**Established, do not re-teach:**
- `state` gates; a `pi_…` id is an attempt, not a receipt
- `unpaid` → the link is the only recovery
- Retry is for dangling (`state=none` + stamp) exclusively
- `unpaid` is a normal resting state, not a failure

**Implication for ZPD:** the Payment-row layer is solid enough to build
on. Stop teaching *what the row says*; start teaching *why the design
produces those rows* — i.e. the mechanics underneath (transactions,
record-first ordering, the Stripe/DB boundary), and the production
layer where the row's assumptions meet a real account.

Baseline caveat from [[0001-inverted-baseline-decisions-fluent-mechanics-thin]]
still holds: this was a *judgement* question, which plays to his
strength. It is NOT evidence that async, transactions, or SQLAlchemy
have landed — none of that has been taught yet.
