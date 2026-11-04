# Orchestration, reservation, pickup and testing — Tej Kiran

This feature extends the existing intake implementation. It consumes committed submission and eligibility events, coordinates versioned work, persists recipient acceptance and driver commitments, records pickup/delivery, and exposes scoped status/recovery APIs. It does not replace donor review or the shared deterministic eligibility policy.

The subsequent [AI Orchestrator Agent](orchestrator-agent.md) adds model-driven tool selection and a persistent decision audit on top of this workflow. The runtime now requests an orchestrator plan before business dispatch. The original verification counts below describe the first merged workflow revision; the agent runbook describes its additional model-path tests and explicit rules/fallback modes.

## Implemented behavior

- `WorkflowService.consume()` commits an event receipt with the resulting state/next step. Repeated broker delivery has one business effect. The general relay leaves intake request events to the existing intake relay.
- Workflow steps carry donation version, matching round, attempt count, lease token, lease expiry and last safe deadline. Workers calculate outside transactions; stale versions/rounds and superseded leases cannot commit results.
- Submission moves to `matching`, requests persisted intake evaluation with trusted candidate facts, consumes the result, and requests a matching proposal. Offer commit rechecks current recipient/profile/driver facts using the existing policy.
- Acceptance is synchronous: reservation, capacity allocation, donation version/history, outbox and idempotent response commit together. Partial unique indexes backstop one active offer, reservation and pickup assignment per donation. Different donations competing for one recipient serialize the storage-specific capacity rows.
- Release/cancellation credits inbound capacity once. Delivery decrements both inbound and physical free space, completes the reservation, and inserts one impact record per donation. It does not make delivered food disappear from storage.
- Driver assignment serializes the driver row and rejects overlapping assigned/accepted/collected commitments. Driver decline preserves recipient acceptance while requesting another feasible driver. No available driver releases the hold and requests re-matching.
- Only the assigned driver can accept, collect or deliver. Pickup requires explicit handling confirmation and the confirmed quantity; discrepancies require a reviewed adjustment. Timing, route freshness and eligibility are rechecked before collection. Delivery requires explicit confirmation and a current receiving window.
- Deadline/assignment/offer sweepers use database state and locks. Food already collected can become a handling exception, never a new offer. Terminal donations cannot reopen.
- Notifications use stable IDs, leases and bounded attempts. The sandbox provider records local receipts only. A real email/SMS provider must implement the existing notification port; providers without idempotency can deliver duplicates after ambiguous send failures.
- SSE publication holds a PostgreSQL advisory transaction lock while allocating cursors over committed outbox rows. Broker and stream publication markers are independent. Clients receive only events authorized for their selected membership/task, with database replay and seven-day retention.

## Run the local synthetic workflow

Use Python 3.12, Node 22, uv and Docker as described in [setup](../setup.md). In your private `.env`, set:

```dotenv
FOODBRIDGE_ENVIRONMENT=local
FOODBRIDGE_AI_PROVIDER=rules
FOODBRIDGE_ENABLE_LOCAL_INTAKE_DEMO=true
FOODBRIDGE_ENABLE_LOCAL_WORKFLOW_DEMO=true
FOODBRIDGE_NOTIFICATION_MODE=sandbox
```

Then:

```sh
make setup
make up
docker compose exec -T api uv run --no-sync python scripts/seed_workflow_demo.py
make smoke-workflow
```

Compose starts the API, separate workers, intake relay and workflow maintenance process. The smoke test exercises actual HTTP, PostgreSQL/PostGIS, Redis/Celery, reservation, driver pickup/delivery, repeated commands and authenticated SSE replay. It writes clearly synthetic demo records and uses no maps/model/email/SMS credentials. Successful output includes `synthetic: true` and `status: delivered`.

The demo seed preserves existing capacity, windows and memberships. Initial receiving/driver windows last one day. If they have elapsed, use a fresh **separate local demo database** or have the data owner update the fixtures with version checks; rerunning the seed does not overwrite operational state.

For native development, run `make infra`, `make migrate`, and `make seed-workflow-demo`, then run these in separate terminals:

```sh
make api
make worker QUEUE=intake
make worker QUEUE=orchestrator
make worker QUEUE=matching
make worker QUEUE=reservation
make intake-relay
make workflow-runtime
```

The matching worker remains Rushitha's implementation workspace. The coordinator dispatches candidate preparation and ranking to its queue through thin integration tasks; it never waits synchronously for a child Celery result. Production candidate/ranking calls go through `MatchingGateway` in [integrations/workflow.py](../../backend/src/foodbridge/integrations/workflow.py). The default adapter raises an explicit dependency-unavailable outcome. Only the opt-in local demo selects `DemoMatching`; it labels its fixed routes/nearest eligible fixture result synthetic. This is not production matching, a maps integration, or AI evaluation evidence.

## Authorization and client handoff

Business routes verify the existing RS256 JWT/JWKS configuration and resolve active server-managed memberships. `X-FoodBridge-Role` and `X-Organization-ID` select among those memberships; they grant no role or organization access. Multiple memberships require a selection. `GET /api/v1/session` returns the selected actor. Existing donor `/me` and intake clients remain compatible.

For the local workflow demo only, the role header selects a fixed seeded synthetic identity (`donor`, `recipient`, `driver`, `operator`). Both demo flags and sandbox notification mode are rejected outside local development. A supplied invalid bearer token never falls back to a demo identity.

All mutations require a UUID `Idempotency-Key`. Commands use expected versions; clients must refetch after 409. The same actor/route/key/body returns the original committed response; a changed body under that key returns 409. Receipts are retained indefinitely in this MVP (therefore at least seven days). No browser request can directly select a destination status.

Canonical models: [workflow.py](../../backend/src/foodbridge/domain/workflow.py), generated [JSON Schema](../../contracts/workflow.schema.json), [TypeScript](../../apps/web/src/api/generated/workflow.ts), and [OpenAPI](../../contracts/openapi.json). Run `make contracts` after changing wire models. Mithil owns screen integration and the frontend snapshot/reconnect behavior.

| Route | Role | Committed behavior |
| --- | --- | --- |
| `POST /reservations` | Recipient | Accept own active match; 201 reservation and donation version |
| `POST /matches/{id}/decline` | Offered recipient | Close offer; increment round and request re-match |
| `POST /reservations/{id}/release` | Reserving recipient/scoped operator | Release pre-collection hold and capacity |
| `POST /donations/{id}/cancel` | Donor/scoped operator | Cancel own pre-collection donation and release related work |
| `GET /matches`, `/matches/{id}` | Recipient | Own offers with recommendation, state and version |
| `GET /pickups` | Driver | Own assignments with donation snapshot and handling notes |
| `POST /pickups/{id}/accept`, `/decline` | Assigned driver | Versioned assignment acceptance/redispatch |
| `POST /pickups/{id}/confirm-pickup` | Accepted driver | Handling and quantity confirmation |
| `POST /pickups/{id}/confirm-delivery` | Collecting driver | Delivery, capacity accounting and impact |
| `GET /operations/summary` | Scoped operator | Donor-organization status/impact totals |
| `GET /operations/failures` | Scoped operator | Persisted sanitized workflow failures |
| `POST /operations/failures/{id}/replay` | Scoped operator | Audited replay with current donation version |
| `GET /events` | Verified membership | Authorized fetch-SSE replay |

Versioned assignment/offer/release/replay commands use `{"expected_version": 1}`. Donation cancellation uses `{"expected_donation_version": 4}`. Reservation input remains `{"match_id": "<uuid>", "expected_donation_version": 4}`. Pickup additionally requires `handling_confirmed: true` and `observed_quantity_kg`; delivery requires `delivery_confirmed: true`.

SSE uses bearer headers and `Last-Event-ID`, never a token in a URL. Without a cursor it starts at the current publication head; establish the stream before fetching snapshots and reconcile aggregate versions. Explicit `Last-Event-ID: 0` replays retained authorized events. Expired cursors return 409 `stream_cursor_expired` before streaming. Keepalives are comments every 15 seconds. Token expiry and active membership are revalidated while connected. `StreamService.prune()` is an explicit maintenance operation; no automatic pruning is enabled by default.

## Recovery policy

New workflow steps have three attempts with bounded exponential backoff/jitter and a 75-second fenced lease; Celery task limits remain 45/60 seconds. The maintenance loop rediscovers due/abandoned steps and republishes acknowledged broker events lacking consumer receipts after 75 seconds. Abandoned intake evaluation deliveries are republished with the same evaluation/event IDs at most twice before a recorded terminal failure. These delivery retries are distinct from intake's existing transient database/model retries.

After transient dependency exhaustion, the step is explicitly blocked with a persisted failure. The donation remains in its current pre-collection state until operator replay or expiry. Replay adds an audited three-attempt budget without erasing total attempts or changing effect identity. Invalid results fail safely. No replay reopens terminal food or bypasses deadlines.

Changed matching facts can start another `matching -> matching` round with a new aggregate version/history entry. Revalidation is capped at ten rounds. Declined/expired/previously released recipients stay excluded from future rounds. Post-collection expiry records `failed` with `post_collection_handling_exception` and releases outstanding inbound accounting; it never re-matches collected food.

## Verification and remaining dependencies

Local verification on 2026-11-04 passed: `make check` (176 Python unit tests, 6 frontend tests, type/build/format/generated-contract/doc checks), `make integration` (35 real PostgreSQL/PostGIS/Redis tests), the existing donor browser smoke (1 test, run in a Linux Playwright container because macOS blocked Chromium's Mach-port bootstrap), and the full Compose workflow smoke. The latter used separate intake, matching, orchestrator and reservation workers and produced a delivered synthetic donation with HTTP idempotent replay and SSE replay. Backend/web Docker image builds and migration drift checks also passed. The local test services were stopped after verification; volumes were preserved.

```sh
make check
make integration
make smoke-workflow
```

The integration suite creates uniquely named throwaway PostgreSQL databases, applies/checks migrations, verifies an empty-database downgrade/upgrade, and runs separate-connection races. It never truncates the normal development database.

| Workbook scenario | Evidence in `backend/tests/integration/test_workflow.py` |
| --- | --- |
| AT-1 / AT-2 | Eligible offer with explanation; allergen exclusion before ranking |
| AT-3 | One successful concurrent acceptance; separate shared-recipient capacity race |
| AT-4 | Decline increments round and selects another eligible recipient |
| AT-5 | Publish-before-ack crash, duplicate consumption, abandoned evaluation, stale lease/result fencing |
| AT-6 | Unavailable matching/routing port retries, blocks explicitly and supports audited replay |
| AT-7 | No eligible recipient and elapsed deadline produce safe terminal outcomes |

Additional tests cover driver commitment races, driver redispatch, cancel/pickup races, accept/expiry, delivery replay/impact, cross-membership access, stream commit ordering/scope/retention and changed-route revalidation. Unit tests reject unsafe commands, role escalation and nonlocal demo settings. The real running-worker smoke supplements these deterministic failure injections; it is not a production load/chaos campaign.

Before team merge, Rushitha should review the additive recipient/capacity/match storage and migration; Mokshith should review the intake event audience addition; Mithil should review the new generated command/read contracts. The new migration is based on `36120ccc9d0d`; do not create a parallel migration history.

Still required for the full product: Rushitha's live candidate/routing/ranking implementation and data/profile update repositories, configured OIDC provider/provisioning and Mithil's browser login/screens, a real notification adapter, and a chosen shared cloud host with secrets/TLS/backups. The local workflow and test adapters do not certify those integrations. Shared-cloud deployment and a complete recipient/driver browser demo remain team release gates.
