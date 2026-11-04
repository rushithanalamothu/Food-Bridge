# Backend workspace

The Python package is installed from the root `pyproject.toml`; run all commands from repository root. See [setup](../docs/setup.md), [design](../docs/design.md) and [planned APIs](../docs/architecture/api.md).

`api/` exposes the gateway. `domain/` defines shared schemas/states. `agents/` contains four separate queue consumers. `db/` owns common persistence; `integrations/` contains provider interfaces/adapters. Keep domain code independent of all frameworks and infrastructure. Each agent folder’s README describes its handoff contract.

Health, intake and Tej's backend workflow are implemented. See [the intake runbook](../docs/features/intake.md) and [workflow runbook](../docs/features/workflow.md). The latter covers durable orchestration, transactional reservation/capacity, driver pickup/delivery, notification requests and authorized SSE. Live candidate/routing/ranking services remain Rushitha's work; the opt-in local adapter is explicitly synthetic.
