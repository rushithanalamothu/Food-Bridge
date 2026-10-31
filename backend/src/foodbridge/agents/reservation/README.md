# Reservation agent — Tej Kiran

Transactional acceptance/release, capacity accounting, driver assignment, pickup/delivery and notification requests.

Current status: queue entry point and diagnostic `foodbridge.reservation.probe` only. No business workflow is implemented here yet.

- Input: Verified actor + typed command + expected version; immutable workflow event IDs.
- Output: Committed reservation/assignment/snapshot + history/outbox; conflicts are explicit and rollback all allocation effects.
- First task: Implement concurrent accept and shared-recipient capacity races before connecting the acceptance UI.

Consume only the `reservation` queue. Register tasks as `foodbridge.reservation.<verb>`. Use shared domain types and repositories; keep provider calls bounded and outside write transactions. See the repository design, events and team implementation plan under `docs/` before changing cross-agent interfaces.
