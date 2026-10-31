# Development setup

## Tools

Use Python 3.12 and Node 22. `uv sync` honors `.python-version`; `nvm use` honors `.nvmrc`. Install uv from its [official instructions](https://docs.astral.sh/uv/getting-started/installation/). Docker needs Compose v2 and a running engine. On Windows use WSL2 + Docker Desktop and run repository commands inside WSL. GNU Make is a convenience; equivalent commands are shown below.

The Vite packages support Node 20.19+/22.12+; Node 22 is the shared baseline. Use `npm ci` and `uv sync --locked` after pulling lockfile changes. Do not regenerate a lockfile to repair a local installation unless dependencies are intentionally changing.

## Quick start (hot reload)

From the repository root:

```sh
cp .env.example .env
uv sync --locked
npm ci
docker compose up -d db redis
uv run alembic -c backend/alembic.ini upgrade head
```

Then separate terminals:

```sh
uv run uvicorn foodbridge.api.main:app --reload --host 127.0.0.1 --port 8000
```

```sh
npm run dev
```

Frontend: <http://localhost:5173>. API docs: <http://localhost:8000/docs>. Vite proxies `/api` to port 8000, keeping browser requests on the same origin. Health and intake routes are available. The donor screen is connected to persisted drafts/submission; other role pages are placeholders. Follow [the intake runbook](features/intake.md) to enable the local demo identity and worker.

A worker example:

```sh
make worker QUEUE=intake
```

Use `orchestrator`, `intake`, `matching` or `reservation`; one process consumes its named queue. The current tasks only verify registration. Business task handlers/outbox polling are subsequent implementation work. On macOS, prefer containerized workers when testing process termination/limits.

## Entire stack in containers

```sh
make up
```

Compose starts DB and Redis health checks, runs migrations once, then starts the API, four worker processes and a Vite development server. The frontend proxies to the API container internally. Container services use `db`/`redis` hostnames; native services use `localhost`. Compose deliberately uses local-only example credentials and loopback-bound ports, with no cloud secrets. It is **not** a production deployment manifest.

This profile copies application source into images; rebuild after code changes (`docker compose up --build -d`). Use native API/web commands for hot reload. Avoid starting native and containerized API/web instances on the same ports.

The official `postgis/postgis` image is amd64-only. Compose sets `platform: linux/amd64` for DB so Apple Silicon can use Docker emulation. Enable emulation in Docker Desktop. See the upstream [image support notes](https://github.com/postgis/docker-postgis). Postgres 16 uses `/var/lib/postgresql/data`; do not change to the Postgres 18 volume layout without a migration/backup plan.

## Checks

```sh
make check
make integration
```

`make check` runs pure/backend/frontend tests, format/type/build checks, contract drift, local documentation links and Compose configuration validation. It does not need a running DB/Redis. `make integration` requires migrated real services and checks PostGIS, Redis and migration head; more integration scenarios land with each business feature. CI provides those services automatically. A skipped infrastructure test is not proof a reservation transaction works.

## Contracts and fixtures

```sh
make contracts
uv run python scripts/generate_synthetic.py
```

The generator writes `data/generated/scenario.json` with fixed seed and a fixed base clock: 10 donors, 6 recipients, 5 drivers, 20 listings. It does not load the database, reserve food or send tasks. For an interactive future-dated dataset, pass an explicit offset-bearing base time:

```sh
uv run python scripts/generate_synthetic.py --seed 2026 --base-time 2026-11-02T20:00:00+00:00
```

Evaluation uses the fixed scenario clock, never wall-clock `now`. Do not change fixtures to today’s date just to make tests pass.

## Useful diagnostics

```sh
docker compose ps
docker compose logs --tail=100 api intake matching reservation orchestrator
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
uv run alembic -c backend/alembic.ini current
```

- **Cannot connect to Docker daemon:** start Docker Desktop/Engine. Valid `docker compose config` is not a running container test.
- **Port already used:** set `FOODBRIDGE_DB_PORT` / `FOODBRIDGE_REDIS_PORT` in `.env`, update the native `FOODBRIDGE_DATABASE_URL` / `FOODBRIDGE_REDIS_URL` to the same ports, and recreate DB/Redis. Compose containers keep using their internal service ports. For API/web collisions, update bindings and the API proxy together.
- **Readiness 503:** check both DB/PostGIS and Redis; liveness 200 only proves the API process responds.
- **Import error:** run from repository root and use `uv run`; do not set ad hoc `PYTHONPATH` values.
- **Stale generated contract:** edit canonical Python types, run `make contracts`, commit all changed outputs.
- **Database migration conflicts:** coordinate with Rushitha; do not delete shared volumes or edit already-merged migration history.
- **Frontend requests return HTML:** confirm Vite’s `/api` proxy target. A malformed response is rejected rather than shown as connected.

`make down` stops containers while preserving volumes. Deleting volumes is an explicit destructive reset, not a normal setup command. `.env` is private and ignored; `.env.example` is the documented public configuration surface. Client bundles may contain no secrets, including `VITE_*` values.
