# FoodBridge

FoodBridge connects surplus-food donors with eligible recipient organizations and coordinates pickup before the food’s safe-use deadline. This repository is the shared implementation foundation for the four-person project team.

**Intake feature:** [run and integrate the donor workflow](docs/features/intake.md).

**Start here:** [setup](docs/setup.md) → [system design](docs/design.md) → [your workstream](docs/team/ownership.md) → [first tasks](docs/team/implementation-plan.md).

## What runs today

- FastAPI health, donor identity, persisted draft/confirmation, donation snapshots and intake evaluation endpoints.
- React donor description/review/submission flow; recipient, driver and operations workspaces remain placeholders.
- Four worker queues, an implemented intake eligibility worker and an intake outbox relay.
- PostgreSQL/PostGIS + Redis setup, intake/identity/outbox tables and versioned migrations.
- Canonical Python domain contracts, generated JSON Schema/TypeScript, state-transition guards, fixtures and a deterministic data generator.
- Unit tests, infrastructure integration tests, formatting checks and CI.

**The complete donation pipeline is still under development.** Intake is implemented through persisted donor confirmation and eligibility evaluation. Gateway login/provider provisioning, matching/ranking, recipient capacity persistence, transactional reservation, SSE and notifications remain assigned work. Verified JWT and an opt-in local demo identity are available for intake integration. [The implementation plan](docs/team/implementation-plan.md) tracks these gaps.

## Local start

Install Python 3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/), Node 22 (`nvm use`), Git and Docker Desktop/Engine with Compose v2. Node 20.19+ can run the selected frontend packages; Node 22 is the team default.

```sh
cp .env.example .env
make setup
make infra
make migrate
```

In separate terminals:

```sh
make api
```

```sh
make web
```

Open <http://localhost:5173>; API docs: <http://localhost:8000/docs>. The root page reports API process reachability. Readiness is <http://localhost:8000/api/v1/health/ready> and requires PostGIS and Redis.

Alternatively, `make up` starts the entire containerized development stack, including workers and the web shell. See [setup](docs/setup.md) for Apple Silicon, Windows and troubleshooting.

## Repository map

| Path | Purpose | Lead |
| --- | --- | --- |
| `apps/web/` | One React codebase, separate role workspaces | Mithil |
| `backend/src/foodbridge/api/` | Gateway, authorization, HTTP/SSE adapters | Tej Kiran |
| `backend/src/foodbridge/agents/intake/` | Extraction, urgency, deterministic eligibility | Mokshith |
| `backend/src/foodbridge/agents/matching/` | Candidate search, ranking, routes, baseline | Rushitha |
| `backend/src/foodbridge/agents/orchestrator/` | Dispatch, retries, recovery, re-matching | Tej Kiran |
| `backend/src/foodbridge/agents/reservation/` | Reservation, assignment, pickup, notifications | Tej Kiran |
| `backend/src/foodbridge/domain/` | Shared contracts and workflow states | Shared, consumer review required |
| `backend/src/foodbridge/db/`, `backend/migrations/` | Database model and one migration history | Rushitha, affected owner reviews |
| `contracts/` | Generated schemas and valid cross-team examples | Shared |
| `config/` | Versioned policy/ranking settings | Mokshith + Rushitha |
| `data/`, `evaluation/` | Reproducible synthetic scenarios and experiments | Rushitha |
| `docs/` | Design, contracts, onboarding, ownership and decisions | All owners |
| `meetings/` | Historical project notes | Preserved |

The UI concept is in [docs/design/ui/foodbridge.html](docs/design/ui/foodbridge.html); it uses simulated data and does not define backend behavior.

## Before your first change

Read [CONTRIBUTING.md](CONTRIBUTING.md). Create a short feature branch from current `main`; keep the feature’s tests, implementation and docs together. Shared schema, lifecycle and migration changes require a consumer review. Run `make check` before opening a pull request; run `make integration` for database/queue changes with services running.

Project brief: FoodBridge Workbook 2, October 2026, especially chapters 3–8. Ownership follows section 8.1a rather than the earlier workbook-chapter assignments in meeting notes.
