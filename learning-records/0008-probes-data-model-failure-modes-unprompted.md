# Noah now probes data-model failure modes unprompted

During a build session (2026-07-21, not a lesson), Noah twice reached
for the failure mode of a design without being prompted — a change from
the earlier pattern of answering questions put to him.

**Evidence:**

1. Unprompted, mid-task: "what if someone uses the same phone number as
   someone else." This is a real hole and it was not on the 29-item UI
   audit. Identity is the phone and `Attendee.phone` is globally
   unique, so two people on one number silently become one row: one
   inherits the other's `/r/` link and saved card, and the split
   divisor undercounts. The nastier variant — someone typing the
   *planner's* number and inheriting the never-charged skip — is the
   same mechanism.
2. Given the direct-payment design fork, he independently specified
   two-party confirmation ("he can mark paid but attendee paid has to
   be confirmed by planner") and, in the same breath, anticipated the
   over-collection case ("if we over collect, it would be displayed
   and shown to attendee") before it was raised with him.

**The honest caveat:** asking the right question is not the same as
deriving the fix. In both cases the mechanism analysis — silent merge,
orphaned card, claim-as-flag-not-state, expire-the-link-before-the-
paid-write — was supplied to him, and he approved rather than
constructed it. What the evidence supports is a raised floor on
*noticing*, not yet on *resolving*.

**Implication:** lessons can now invert. Instead of "here is the
invariant, here is why", give him a diff or a scenario and ask what
breaks — his hit rate on spotting the break is high enough that the
exercise will produce signal rather than frustration. Good candidates
he has not seen: the walk-in re-split (a refund path that does not
exist yet), and what happens if two planners share one connected
account. Pair this with [[0007-three-account-topology-is-the-live-gap]]:
teach the topology, then hand him a broken scenario in it.
