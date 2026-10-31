# Backend workspace

The Python package is installed from the root `pyproject.toml`; run all commands from repository root. See [setup](../docs/setup.md), [design](../docs/design.md) and [planned APIs](../docs/architecture/api.md).

`api/` exposes the gateway. `domain/` defines shared schemas/states. `agents/` contains four separate queue consumers. `db/` owns common persistence; `integrations/` contains provider interfaces/adapters. Keep domain code independent of all frameworks and infrastructure. Each agent folder’s README describes its handoff contract.

Health and the donor intake slice are implemented. Intake adds minimal identity/draft/donation/outbox persistence and an eligibility worker. Matching/reservation/stream entities remain assigned work. See [the intake runbook](../docs/features/intake.md). Add features with tests and an honest status update; do not create fake successful handlers to fill the folders.
