# Matching agent — Rushitha

Category normalization, PostGIS candidate search, route estimates, constrained ranking and distance-only baseline.

Current status: diagnostic probe plus thin `prepare`/`rank` queue integration tasks for Tej's coordinator. Production candidate/routing/ranking logic remains unimplemented. The default gateway reports dependency unavailable; only the explicitly enabled local demo uses synthetic matching. See the [workflow handoff](../../../../../docs/features/workflow.md).

- Input: Donation/profile versions, matching round and eligible candidate IDs under one policy version.
- Output: MatchRecommendation proposal or exhausted reason; do not create reservations or bypass eligibility.
- First task: Deliver routing fake/provider interface and distance-only strategy with no-candidate/route-timeout tests.

Consume only the `matching` queue. Register tasks as `foodbridge.matching.<verb>`. Use shared domain types and repositories; keep provider calls bounded and outside write transactions. See the repository design, events and team implementation plan under `docs/` before changing cross-agent interfaces.
