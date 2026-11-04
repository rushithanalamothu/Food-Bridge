# AI Orchestrator Agent

The orchestrator now has an observe → model plan → tool execution → feedback loop. This extends the previously merged deterministic workflow implementation. When the app-wide AI provider is configured, the orchestrator worker calls that model to select its next supported action. The database transaction layer still validates state, versions, deadlines, eligibility and capacity.

## What the agent does

`foodbridge.orchestrator.plan_step` runs on the orchestrator queue. It observes the current donation status, workflow stage, matching round, input version, attempt budget, sanitized failure code, remaining safe time, previous step outcomes and its last decision outcome. It sends these structured facts to `integrations.ai.generate_structured` and receives an `OrchestrationPlan`.

The model chooses from an observation-specific tool allowlist:

| Tool | Behavior |
| --- | --- |
| `prepare_candidates` | Dispatch candidate preparation to the matching agent. |
| `rank_candidates` | Dispatch the matching/ranking stage after intake. |
| `coordinate_pickup` | Dispatch driver coordination to the reservation agent after acceptance. |
| `retry_current_agent` | Retry the current eligible stage when prior attempts exist and budget remains. |
| `refresh_eligibility` | Start a fresh eligibility round from the matching stage. |
| `wait` | Defer 5–30 seconds when sufficient deadline slack remains. |
| `escalate_operator` | Persist a blocked failure for operator review/replay. |

The agent is not merely an LLM-generated explanation attached to the previous router. Its validated tool choice determines whether work is dispatched, retried, deferred, refreshed or escalated. Each next observation includes the previous decision outcome and worker feedback.

The model returns a concise operational summary, not private chain-of-thought. It receives no donor description, address, contact details or API credentials. It cannot supply arbitrary task names, Python, SQL, URLs, recipient IDs or driver IDs.

## Execution and recovery

Planning has a separate 75-second lease in the existing workflow step JSONB metadata. Model calls run outside database transactions. On return, the agent checks the current lease token, step/donation version, matching round, action allowlist and deadline again. Cancellation, expiry or a superseding plan prevents execution.

Accepted dispatch choices create an `orchestrator.dispatch_requested.v1` outbox command in the same transaction as the saved decision. The relay/consumer dispatches only a server-mapped task on the existing matching/reservation queues. Queue payloads contain persisted IDs and a dispatch token; model summaries and observations stay in the database. Child workers verify that token and retain their existing business-effect leases and idempotency checks.

A send-before-receipt crash may redeliver a command; fenced worker claims prevent an extra committed effect. A killed planner is retried after its planning lease expires. A worker retry can be planned again at its persisted retry time. Eight planning decisions are allowed per initial step budget; audited operator-added retry budget permits additional bounded planning. Existing step retry limits and the ten-round revalidation cap remain enforced.

Deterministic expiry/recovery sweepers and notification delivery continue independently of model availability. The model cannot reserve food, approve safety, extend deadlines, alter capacity, erase attempts, bypass donor confirmation or reopen terminal donations.

No new database migration is required. Decisions are stored under `workflow_steps.data.orchestrator`, alongside the existing durable workflow data.

## Shared AI configuration

Use the existing [app-wide AI setup](../setup.md#shared-ai-configuration). The orchestrator uses the same resolved `Settings.ai_provider`, `ai_api_key`, `ai_model` and timeout as extraction and other model features. No orchestrator-specific provider, model, SDK, API key or cross-vendor fallback was added.

With an actual provider/key/model configured, new plans use `mode: model`. If the app resolves to `provider=rules` (including no configured API key), the deterministic baseline is explicitly stored as `mode: rules`; no model is called. A provider/network failure uses `mode: fallback` with a sanitized failure code. Invalid model output is recorded as `mode: rejected` and escalated rather than executing the invalid action. Rules/fallback decisions are never presented as successful AI reasoning.

Restart the API/workers/runtime after changing private `.env` configuration. Run the normal `make up` stack, or start `make worker QUEUE=orchestrator` together with the other agents and `make workflow-runtime` in native development. The runtime now queues planning work rather than directly choosing a business worker task.

## Inspect a decision

Authorized operators can read:

```http
GET /api/v1/operations/orchestrator/decisions/{step_id}
Authorization: Bearer <access-token>
```

To discover a donation's recent step decisions, use `GET /api/v1/operations/orchestrator/decisions?donation_id={donation_id}&limit=25` (maximum 100). The list is scoped to the same authorized donor organization and ordered by the latest round/version.

The response is scoped to the donation's donor organization and contains the step status plus decision history: provider/model, prompt version, observation, selected tool, summary, execution outcome and fallback/rejection reason. It exposes no credentials. Existing operator role/resource checks apply. Local demo operators use the existing opt-in identity mechanism.

Canonical models live in `domain/orchestration.py` and are included in the existing generated workflow schema/TypeScript and OpenAPI. An example decision is `mode=model`, `tool=prepare_candidates`, `outcome=dispatched`; `mode=rules` explicitly identifies a non-model smoke run.

## Verification and limits

Unit tests reject invented tools, changed IDs/versions, out-of-order stages and unsafe delays. Real PostgreSQL tests exercise the shared AI client's structured-output HTTP protocol using a mock transport, persisted decision/dispatch, wait/feedback, revalidation, invalid-plan escalation, cancellation during a model call, deadline expiry, lease fencing, explicit fallback and send-before-receipt recovery. Existing reservation, capacity and pickup race tests remain in place.

Run `make check`, `make integration` and `make smoke-workflow`. CI/local smoke uses `FOODBRIDGE_AI_PROVIDER=rules` so it needs no live AI credentials. Model-path tests use controlled responses and do not claim a live-provider quality evaluation. A real key/model is required to exercise actual model reasoning in your running environment.

This change does not complete Rushitha's production matching/routing implementation or Mithil's frontend. It changes the orchestrator's planning behavior and preserves those integration ports.

Local verification for this change passed `make check` (187 Python unit tests, 6 frontend tests and repository contract/type/build checks), `make integration` (48 PostgreSQL/PostGIS/Redis tests), and a real HTTP/broker/four-worker smoke through delivery. The smoke recorded three orchestrator decisions with `mode=rules`; no live AI key was configured or used. Model-path tests exercised the existing structured-output client with controlled HTTP responses. A fresh Docker image rebuild was not completed in this sandbox because registry metadata retrieval stalled; the worker smoke ran the updated source natively against real Docker-hosted PostgreSQL/PostGIS and Redis.
