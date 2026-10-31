# FoodBridge repository guidance

This repository is a scaffold for a four-person academic project. Start with `docs/design.md`, `docs/team/ownership.md` and `docs/team/implementation-plan.md`. Preserve the distinction between implemented foundation and planned business functionality.

- Use Python 3.12 through uv and Node 22/npm. Keep `uv.lock` and `package-lock.json` committed.
- Python source lives under `backend/src/foodbridge`; do not create a second backend package or migration history.
- All role UIs share `apps/web`; keep role work within `src/features/<role>` and reuse typed API wrappers.
- `domain/contracts.py` and `domain/states.py` are shared vocabulary. Run `make contracts` after wire changes. Never hand-edit generated JSON Schema/TypeScript/OpenAPI files.
- Pure domain code may not import FastAPI, Celery, ORM or provider clients.
- Donor confirmation, deterministic eligibility, version checks, deadlines and transactional reservation are mandatory boundaries. AI output does not override them.
- Business effects require durable outbox/receipt/transaction semantics; Celery late acknowledgement does not provide exactly-once effects.
- Add real implementation or explicit placeholders. Do not return successful matching/reservation/authentication responses from unfinished handlers.
- Run `make check`; run `make integration` with real PostgreSQL/PostGIS and Redis for data/queue changes. Document checks that could not be run.
- Coordinate schema/migration changes with the data owner and producer/consumer contracts with affected owners. Local fixes, documentation and reversible edits do not require extra user approval.
- Keep secrets/real user data out of Git, logs, frontend bundles and queue payloads. Keep historical `meetings/` notes unchanged unless specifically correcting them.
