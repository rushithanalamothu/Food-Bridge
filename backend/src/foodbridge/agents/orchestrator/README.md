# Orchestrator agent — Tej Kiran

Durable dispatch, matching rounds, task leases, retry budget, timeout/recovery and dead-letter replay.

The [AI Orchestrator Agent](../../../../../docs/features/orchestrator-agent.md) now observes workflow state, calls the app-wide model, selects a supported tool and records the outcome for the next decision. It runs on `foodbridge.orchestrator.plan_step`. Configured AI uses model planning; disabled/unavailable AI is explicitly labeled rules/fallback. Transaction and food-safety checks remain deterministic.

Implemented: durable submission/result consumption, workflow receipts/steps, fenced leases, bounded retries, re-matching, recovery and audited replay. See the [workflow runbook](../../../../../docs/features/workflow.md). Live matching/routing uses an explicit integration port; the local demo adapter is synthetic.

- Input: Committed donation/event IDs, aggregate version and correlation ID.
- Output: Next versioned step command or an explicit persisted outcome; never directly call another agent handler.
- Verification: `make check`, `make integration`, then the runbook's real worker smoke.

Consume only the `orchestrator` queue. Register tasks as `foodbridge.orchestrator.<verb>`. Use shared domain types and repositories; keep provider calls bounded and outside write transactions. See the repository design, events and team implementation plan under `docs/` before changing cross-agent interfaces.
