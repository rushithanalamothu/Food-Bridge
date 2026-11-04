# Reservation agent — Tej Kiran

Transactional acceptance/release, capacity accounting, driver assignment, pickup/delivery and notification requests.

Implemented: synchronous accept/decline/release/cancel and driver pickup/delivery commands, transactional capacity accounting, asynchronous assignment and sandbox notification delivery. See the [workflow runbook](../../../../../docs/features/workflow.md). Real notification delivery and live routing remain adapter integrations.

- Input: Verified actor + typed command + expected version; immutable workflow event IDs.
- Output: Committed reservation/assignment/snapshot + history/outbox; conflicts are explicit and rollback all allocation effects.
- Verification: `make integration` covers concurrent accept/shared-capacity/driver races and delivery replay; `make smoke-workflow` exercises actual workers.

Consume only the `reservation` queue. Register tasks as `foodbridge.reservation.<verb>`. Use shared domain types and repositories; keep provider calls bounded and outside write transactions. See the repository design, events and team implementation plan under `docs/` before changing cross-agent interfaces.
