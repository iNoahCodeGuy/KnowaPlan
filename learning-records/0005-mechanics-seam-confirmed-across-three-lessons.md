# The miss pattern is consistent: every miss is the concept→code seam

Lesson 3 quiz: 2/4. Missed Q3 (who commits after `charge_share` —
answer settlement.py, because payments.py holds no session) and Q4
(internal-hostname links — answer the Dockerfile proxy flags). Got
Q1 and Q2 (both about who-may-write-state, via the transition table)
right.

**This is the third data point and they line up exactly.** Across
all misses — review Q6 (`transfer_data` no amount), L3 Q3 (the
commit boundary), L3 Q4 (proxy flags) — every wrong answer is the
moment a claim stops being about the *design* and lands on the
*mechanism*: a specific parameter, a function signature, a runtime
flag. Every design-layer / state-ownership question is answered
cleanly. The gap is not fuzzy understanding of the system; it is the
concept→substrate mapping, and it is narrow and nameable.

Sharpens learning-records/0001 and 0004: 0004 localized it to L2;
this confirms it generalizes across the codebase. Told Noah the
pattern explicitly (metacognitive framing) so he can target it.

**Q3 specifically matters most:** it is the commit-boundary / record-
first mechanism — the spine of the money path and the next queued
concept. Missing it means record-first is owned as a *decision* but
not yet as *machinery* (which commit, owned by whom, in what order).

**Response built:** Lesson 4 (lessons/0005-follow-one-charge-
through-the-code.html) — a line-by-line trace of one $30 charge:
settle_event stamp + COMMIT #1 → `charge_share` (no `session` param,
so structurally cannot commit; mutates in memory; `transfer_data`
no amount = Q6 in situ) → `_collect` COMMIT #2. The knockout for Q3
is that `charge_share`'s signature has no session — placement
enforced by the parameter list. Closes Q3 + Q6 and re-grounds
Lesson 1's crash/row map in the exact lines. UNVERIFIED — no quiz
results yet.

**Still open:** L3 Q4 (deployment / proxy / request.base_url) is a
separate territory, deliberately NOT folded into Lesson 4; explained
in prose and queued as its own deployment lesson. Also, the
transactions-concept lesson ("what a commit guarantees") may now be
partly pre-empted by Lesson 4's concrete version — reassess whether
it's still needed as a standalone or can be folded into the async
lesson.

**Evidence:** self-reported 2/4 with Q3+Q4 the misses; the two
correct were the transition-table questions.
