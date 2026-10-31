# Backend workspace

The Python package is installed from the root `pyproject.toml`; run all commands from repository root. See [setup](../docs/setup.md), [design](../docs/design.md) and [planned APIs](../docs/architecture/api.md).

`api/` exposes the gateway. `domain/` defines shared schemas/states. `agents/` contains four separate queue consumers. `db/` owns common persistence; `integrations/` contains provider interfaces/adapters. Keep domain code independent of all frameworks and infrastructure. Each agent folder’s README describes its handoff contract.

Only health endpoints and worker probes are implemented. The first migration enables PostGIS; mapped business entities and transactions remain assigned work. Add features with tests and an honest status update; do not create fake successful handlers to fill the folders.
