## 2026-05-26: Extended Authorization requires platform approval
**Finding:** request_extended_authorization="if_available" raises
InvalidRequestError in test mode — Stripe requires explicit platform
approval for flexible payment features, even with the if_available flag.
**Impact:** RSVPs cannot be accepted more than 7 days before an event
until Stripe approves the platform. Not blocking for v0 dogfood phase
(friend group, known schedule). Must be resolved before opening to
strangers.
**Action:** Contact Stripe support to request flexible payments eligibility
before end of Phase 1.
**Replaces:** Prior assumption in decisions.md that Extended Authorization
was available from day one.