# Workstreams and ownership

This split follows Workbook 2 §8.1a. Earlier chapter/meeting-note assignments are historical, not a second implementation ownership scheme. A lead coordinates the area; any teammate can contribute through a reviewed PR.

| Person | Main workspace | Deliverables | Depends on | Reviews with |
| --- | --- | --- | --- | --- |
| Mokshith | `backend/src/foodbridge/agents/intake/` | Extraction draft, donor confirmation rules, urgency, food-safety/dietary/capacity eligibility, donation validation | Canonical contracts; recipient/route inputs from Rushitha | Mithil for donor UI; Rushitha for policy inputs; Tej for workflow outcomes |
| Mithil | `apps/web/src/` | Role UIs, shared components, typed API client, SSE/reconnect, responsive/a11y/error states | Stable contract examples; auth adapter; API snapshots/SSE | Each corresponding backend owner |
| Rushitha | `backend/src/foodbridge/agents/matching/`, `db/`, migrations, `data/`, `evaluation/` | Schema, PostGIS candidates, route adapters, match features/ranking, distance-only baseline, reproducible evaluation | Intake’s hard-policy contract; driver feasibility input | Mokshith for eligibility; Tej for transaction constraints; Mithil for offer read model |
| Tej Kiran | `api/`, `agents/orchestrator/`, `agents/reservation/`, integration tests, deployment | Auth gateway, durable dispatch/outbox, retries/recovery, reservation, pickup, notifications, SSE, AT-1–7 | Domain contracts and database repositories | Affected domain owner; Mithil for client flows |

## Shared files need a named reviewer

| Shared surface | Integrator | Required consumer review |
| --- | --- | --- |
| `domain/contracts.py`, generated schemas/types | Tej coordinates | At least one producer and one consuming owner |
| `domain/states.py`, status/reason vocabulary | Tej | Mokshith + affected UI/matching owner |
| `db/`, migration history | Rushitha | Owner of affected business transaction |
| `config/matching.json` / eligibility policy | Mokshith + Rushitha | Tej for lifecycle impact |
| root dependency files and lockfiles, Compose, CI | Tej coordinates | Teammate whose runtime is affected |
| `integrations/ai.py`, `Settings.ai_*`, AI environment wiring | Tej coordinates shared runtime; Mokshith maintains current intake adapter | Rushitha for future ranking; each affected feature owner. One app-wide provider/key/model; no per-feature vendor clients |
| global frontend styles, router, shared components | Mithil | Feature owner if behavior changes |
| design and API/event documents | All authors own their changes | Consuming owners for changed interfaces |

GitHub `CODEOWNERS` requests reviews using verified collaborator handles. It is not a permission system and does not enable branch protection by itself. Configure one required approval and required CI checks in repository rules when an administrator is available. The current contributor account can push but cannot administer repository rules; do not assume they are active.

## What each person can start independently

- **Mokshith:** pure extraction-to-proposal conversion with explicit missing fields, deadline/quantity tests, and the hard-policy function. Use fixture recipient/route inputs until repositories land. No database or model credentials needed for unit tests.
- **Mithil:** build the donor review form and other role UI states against contract fixtures. Keep mocks in the feature/test layer, label synthetic state, and use one API wrapper. Do not create a second set of wire enums or put status mutations inside components.
- **Rushitha:** business-table migration and repositories first; PostGIS queries and routing ports next. Deliver distance-only strategy before adding model ranking so everyone has a deterministic integration path.
- **Tej:** OIDC verification/membership contract, outbox/step leases and acceptance commands with fake providers. Review donation/table contracts before implementing reservation locks. Reserve unique effect IDs from the start.

## Handoff checklist

A module is ready for another owner when its PR includes:

1. Typed input/output or command/event schema, units and versioning.
2. One valid example and at least one rejected/conflict/timeout example.
3. Deterministic tests; database-sensitive behavior proven on PostgreSQL.
4. Auth/resource access rules if public-facing, with negative tests.
5. Updated docs, migration and generated artifacts where applicable.
6. Clear implemented/unimplemented status and exact command to verify it.

Work in feature branches such as `feat/intake-draft-review`, `feat/web-donor-form`, `feat/data-core-model` and `feat/reservation-command`. Names are suggestions, not long-lived owner branches. Keep `main` integrated and runnable; avoid one branch per person that diverges for months.

All contributors adding model-backed behavior must follow [shared AI setup and integration rules](../setup.md#shared-ai-configuration). Reuse `integrations.ai.generate_structured`; feature prompts and output schemas may differ, but provider/key/model settings are shared across the app.
