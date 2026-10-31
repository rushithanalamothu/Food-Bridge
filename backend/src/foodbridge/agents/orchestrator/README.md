# Orchestrator agent — Tej Kiran

Durable dispatch, matching rounds, task leases, retry budget, timeout/recovery and dead-letter replay.

Current status: queue entry point and diagnostic `foodbridge.orchestrator.probe` only. No business workflow is implemented here yet.

- Input: Committed donation/event IDs, aggregate version and correlation ID.
- Output: Next versioned step command or an explicit persisted outcome; never directly call another agent handler.
- First task: Implement outbox relay + receipt/step lease with duplicate/crash/stale-round tests.

Consume only the `orchestrator` queue. Register tasks as `foodbridge.orchestrator.<verb>`. Use shared domain types and repositories; keep provider calls bounded and outside write transactions. See the repository design, events and team implementation plan under `docs/` before changing cross-agent interfaces.
