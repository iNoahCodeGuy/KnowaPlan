# Q6 miss localizes the gap: concept solid, concept↔code mapping thin

On the interleaved review (lessons/0004), Noah self-reported 6/7 —
the sole miss was Q6, the one question asking *which line of code*
causes the full transfer (`transfer_data` with no `amount`). He got
Q2 (platform eats the fee) and Q4 (Standard changes nothing) right,
and both money-losing diagnosis traps — Q3 (dangling) and Q5
(`pi_…` is not a receipt) — right.

**What this localizes:** the money-flow *concept* and the
"plausible knobs don't work" *trap* are solid; the row-reading skill
from Lesson 1 is durable (corroborates learning-records/0002). The
fuzzy spot is precise: the **positive mechanism at the code level** —
mapping "the full amount transfers and the platform eats the fee"
onto the actual parameter (an *omitted* `amount`, not a mis-set
knob). Knowing what does NOT cause it ≠ knowing what does.

This sharpens the inverted baseline (learning-records/0001): the gap
is not concept, it's the concept→code mapping. He reasons fluently
about the design and is thin where a claim has to touch a specific
line.

**Implication for the requested 1&2 deepening** (he asked for a
"stronger understanding" of both, right after this quiz): go to the
CODE level, not more diagnosis reps. `charge_share()` in
[[app/payments.py]] is the convergence point — one function holding
both the Lesson 1 row-writing (record-first stamp check, state →
paid/unpaid, the CardError→unpaid decline path) and the Lesson 2
money-routing (`transfer_data`, `on_behalf_of`, the idempotency
key). A line-by-line read deepens both lessons at once and targets
the Q6-type gap directly. Recommended as the next lesson after he
finishes Lesson 3; proposed to him, awaiting his confirmation (he
may prefer diagnosis reps or the money-accounting angle instead).

**Evidence:** self-reported 6/7 with Q6 the only miss; Q6 is the
only pure code-mechanism question in the set.
