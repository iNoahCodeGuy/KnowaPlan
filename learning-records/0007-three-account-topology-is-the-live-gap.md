# The platform ↔ connected-account topology is the live gap

Noah does not yet hold the three-account picture — cardholder,
platform, connected account — and this is now the highest-value thing
to teach, ahead of async/await.

**Evidence, all from 2026-07-21 and all behavioral rather than
quiz-shaped:**

1. Mid-test he asked, "so you want me to charge the card and return
   the money because attendees were hypothetically absent for this?"
   — reading the refund rehearsal as an app flow (mark-absent) rather
   than as an out-of-band dashboard action against a different
   account.
2. Then, "if I get charged a dollar and my stripe account is linked to
   my personal bank account, does that mean I will get one dollar
   back?" — the question only arises if platform-you and
   connected-account-you are still one undifferentiated "my Stripe".
3. **The strongest signal is not a question.** After being told twice,
   in writing, to tick "reverse the associated transfer", he refunded
   both charges and the transfers stayed `reversed: false`. He
   reported "refunds are complete" in good faith. The refund was
   visible and intuitive; the reversal was neither, because nothing in
   his mental model says money is sitting in a *second* account that a
   refund doesn't touch.

**Why it matters more than it looks.** One-shot settlement is locked
for v1 — no in-app re-marking after settle — so a dashboard refund
*with* reversal is the ONLY correction mechanism at the 2026-07-29
club night. A refund without the reversal silently drains the platform
balance while the money stays parked in the connected account. Solo
that is harmless bookkeeping (both pockets are his). The moment a
second planner exists it is someone else's money in the wrong place.

**Implication for the curriculum:** teach "the three accounts" next —
concretely, using his own two live charges as the worked example
(fee 33¢ of $1.00 and 35¢ of $1.66; refund returns the full charge to
the card but not the fee; the reversal is what pulls the transfer
back). Do NOT teach it as Connect theory. The lesson should end with
him reading `reversed: true` on his own transfers. This also supersedes
nothing — it sits beside the [[0005-mechanics-seam-confirmed-across-three-lessons]]
finding: the seam there was concept→code, and this one is
concept→*money topology*, which the code lessons never touch because
the topology lives in Stripe, not in the repo.
