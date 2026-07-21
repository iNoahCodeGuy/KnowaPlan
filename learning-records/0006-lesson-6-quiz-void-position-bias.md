# The Lesson 6 score is VOID — the quiz had a position tell

Noah scored 1/5 on the Lesson 6 (settle_event) quiz, then asked "is
there a reason why it's always A?" He was right, and the defect is
mine: across all 33 questions in the workspace the correct answer sat
in slot 1 **82%** of the time, and lessons 3 through 6 were **100%** —
21 consecutive questions, answer-first. Slot predicted the answer, so
a score stopped measuring recall.

**Do not read the 1/5 as evidence of anything.** The failure mode here
is not merely "an easier quiz." It plausibly **inverts** a score: a
learner who notices a long run of slot-1 answers starts avoiding slot 1
on principle. His answer pattern fits that exactly — the four he got
wrong were slots 4, 4, 4, 3 (never slot 1), and the one he got right
was slot 1. So a well-calibrated learner second-guessing an obvious
pattern produces precisely this transcript. The instrument, not the
understanding, is the most likely explanation.

This also weakens — but does not erase — the three earlier data points
in [[0004-q6-localizes-mechanics-gap]] and
[[0005-mechanics-seam-confirmed-across-three-lessons]]. Those quizzes
carried the same bias, and he scored 6/7 and 2/4 on them, which is
inconsistent with blind slot-1 picking; the concept→code seam finding
therefore still stands on its own evidence. But Lesson 6's result
cannot be stacked on top of it.

**Fixed:** every lesson's options were rebalanced to a near-uniform
slot distribution (30/24/24/21), and `assets/check_quiz.py` now fails
any lesson where one slot holds the answer more than half the time, so
this cannot silently return.

**Implication:** the open question — did Lessons 4 and 6 close the
concept→code seam? — is still open, and the curriculum should not
branch on the 1/5. A clean retrieval check on the same material is the
next measurement; until it exists, treat settle_event comprehension as
UNMEASURED rather than failed.
