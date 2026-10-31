# Architecture decision log

Accepted at scaffold creation, 2026-10-30. These choices resolve workbook alternatives and make parallel development possible. A later change adds an entry with context, alternatives, migration/consumer impact and owner; it does not silently replace a team convention.

| ID | Decision | Tradeoff / revisit condition |
| --- | --- | --- |
| ADR-001 | One monorepo and one Python package, four worker modules/queues | Shared versions and easy testing; split packages only if deployment/version independence demands it |
| ADR-002 | One React app with donor/recipient/driver/operations workspaces | Deliberate refinement of workbook’s three-client description; avoids duplicate auth/components/contracts |
| ADR-003 | Celery + Redis, no Kafka in MVP | Fits team scale and workbook option; requires explicit durable outbox/receipts because broker delivery is not exactly once |
| ADR-004 | PostgreSQL 16 + PostGIS 3.6, one Alembic history | Stable common data plane; official image needs amd64 emulation on Apple Silicon |
| ADR-005 | Pydantic contracts generate JSON Schema and TypeScript | One vocabulary; generated OpenAPI represents only implemented routes; drift checks guard integration |
| ADR-006 | Deterministic coordinator and hard-policy gate; LLMs only for bounded extraction/ranking | Prevents model output overriding consistency/safety; no extra agent framework until justified |
| ADR-007 | Entire donation reserved atomically; no partial allocation in MVP | Simpler capacity/driver transactions; splitting needs a new allocation model and contract version |
| ADR-008 | Persisted offer → explicit recipient reservation → separate driver assignment | Distinguishes acceptance from logistics; supports driver retry without losing the recipient |
| ADR-009 | JWT/OIDC verification and organization membership; fetch-based SSE | Standard bearer auth and scoped replay; provider choice is still a scheduled implementation task |
| ADR-010 | No network credentials or live model required for CI | Fake adapters and seeded clocks enable parallel work; live-provider integration is a separate gated test |
| ADR-012 | Intake extraction completes synchronously with a bounded provider timeout; draft POST returns 201; confirmed submission remains 202 with durable handoff | Runs without the unfinished generic orchestrator; later async extraction requires compatible draft lifecycle changes |
| ADR-013 | Local intake demo is an explicit local-only opt-in; shared intake verifies OIDC JWTs and server memberships | No production login/provisioning is invented; gateway integration remains assigned |
| ADR-011 | Scaffold exposes health only; feature routes are honest placeholders | Teammates can run and build now without mistaking simulated business output for implementation |

## ADR-014 — Reconcile intake v0.3 without a second lifecycle

Keep explicit donor confirmation, canonical kilograms, source-backed extraction, app-wide AI settings and the shared donation lifecycle. Model self-reported confidence is replaced by deterministic evidence checks and mandatory donor review. Urgency defaults now match the individual spec (2/6 hours); policy v2 adds configurable intake limits/required fields without disabling safety minima. Packaging is additive JSONB/wire data, so no migration is needed.

Eligibility decisions are separate from aggregate state. The existing outbox events and typed `IntakeService.get_handoff` are the intake boundary; general Orchestrator/Matching dispatch remains assigned work. This avoids advertising a second `ELIGIBLE` state machine or an unfinished workflow as complete. [The alignment record](../specs/intake-v0.3-alignment.md) maps DI/NFR/UT/FT requirements, operational limits, amendments and remaining owners. Producer/consumer review should focus on packaging, policy/result/handoff contracts and policy-version invalidation.

## Technical references

Primary documentation consulted when choosing the foundation:

- [FastAPI multi-file application structure](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [Vite runtime requirements](https://vite.dev/guide/)
- [Celery tasks and late acknowledgement](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Celery Redis visibility and redelivery](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)
- [PostgreSQL row locking and queue-like SKIP LOCKED](https://www.postgresql.org/docs/current/sql-select.html)
- [Compose startup/health dependency conditions](https://docs.docker.com/compose/how-tos/startup-order/)
- [Alembic autogeneration and migration checks](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- [Official PostGIS image/platform support](https://github.com/postgis/docker-postgis)

Exact installed Python/npm versions are in lockfiles, not copied into this table. Revalidate runtime/image compatibility when intentionally updating them.
