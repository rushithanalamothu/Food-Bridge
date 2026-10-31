# Intake and Eligibility — Mokshith

Implemented: conservative text extraction + optional structured model adapter, donor review/confirmation, persisted submission/history/outbox, deadline urgency, deterministic eligibility and an idempotent worker.

Start with [the feature runbook](../../../../../docs/features/intake.md) for exact contracts, local setup, limits and the handoff to matching/orchestration. Canonical types are in `domain/intake.py`; generated artifacts come from `make contracts`.

`policy.py` is provider/DB/framework-independent. `service.py` owns transactions. `extraction.py` proposes unconfirmed fields. `tasks.py` consumes a persisted evaluation ID; `relay.py` publishes only intake evaluation requests. Submission events remain available for Tej's orchestrator. No matching, reservation or capacity mutation is performed here.
