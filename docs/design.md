# FoodBridge implementation design

Status: implementation baseline, 2026-10-30. Source: FoodBridge Workbook 2, chapters 3–8, with technical ownership from section 8.1a. This document turns the workbook’s choices into integration rules; it does not claim the planned features are already implemented.

## 1. Outcome and scope

A donor describes surplus food, confirms structured details and submits a donation. FoodBridge validates the donation, filters eligible recipients, recommends one recipient, obtains acceptance, assigns a feasible driver and records pickup and delivery. A declined or expired offer can trigger another matching round while the food remains usable. Operators can understand each decision and recover failed work.

The academic MVP uses explicitly synthetic organizations, drivers, listings and outcomes. It compares a multi-criteria matcher with a distance-only baseline on the **same eligibility rules, routing inputs and workload**. It must not present simulated outcomes as real food rescued or model validation results.

In scope: the four specialized agents, role-based web surfaces, deterministic eligibility, structured extraction review, urgency prioritization, geospatial candidate search, routing, transactional reservation, status delivery, notifications, reproducible scenarios and evaluation. Out of scope for the first release: payments, consumer food sales, native mobile apps, marketplace chat, multi-stop optimization, autonomous food-safety approval and real partner onboarding. No new infrastructure should be added just to support a deferred feature.

## 2. Architecture choices

| Area | Baseline | Reason |
| --- | --- | --- |
| Web | One React/TypeScript app with four role workspaces | Shares components, auth and contracts; avoids three drifting applications |
| API | FastAPI, `/api/v1`, Pydantic models | One authenticated entry point; explicit wire contracts |
| Python layout | One installable `foodbridge` package with module boundaries | Four people can share contracts without publishing internal packages |
| Workers | Four Celery queues/processes, one shared backend image | Independently runnable agents without four dependency stacks |
| Persistence | PostgreSQL 16 + PostGIS 3.6, SQLAlchemy 2, Alembic | Geospatial queries, transactions and a single migration history |
| Transport | Redis 7.4 + Celery | Workbook option selected; Kafka is deferred |
| Status | Authenticated fetch-based SSE with durable DB replay | Browser updates survive reconnects; Redis pub/sub is only a wake-up hint |
| Integrations | Provider adapters for extraction/ranking, routing, notifications | Core rules remain testable without live credentials |
| Local runtime | Docker Compose; native web/API development also supported | Same dependencies on every laptop |
| Reproducibility | `uv.lock`, `package-lock.json`, fixed scenario seeds and clocks | Comparable installs and evaluation runs |

The workbook names three React clients. Here they are separate role workspaces in one deployable frontend, not separately maintained builds. The four agents remain separate runtime processes. The orchestrator is a deterministic workflow coordinator, not an LLM that can invent state transitions. This is an implementation choice recorded in the [decision log](architecture/decisions.md).

### Deployment boundary

```text
Browser: donor | recipient | driver | operations
                         |
                    FastAPI Gateway
                         |
              domain services + repositories
                         |
               PostgreSQL / PostGIS
                         |
              transactional outbox relay
                         |
                    Redis / Celery
         +---------------+---------------+---------------+
   orchestrator        intake          matching       reservation
       queue            queue            queue            queue
                         |
              LLM / routing / notification adapters
```

Each worker imports domain contracts and only its own agent implementation. Shared domain services/repositories own invariant-preserving transactions. Workers do not call another agent’s task function directly; the orchestrator decides the next action based on persisted state and version. They do not expose public HTTP ports. All browser writes go through the gateway.

The outbox relay, recovery scheduler and business task handlers are planned work; the scaffold currently registers diagnostic tasks only. Four green worker processes do not mean the donation workflow exists.

## 3. Module boundaries

- `api/`: HTTP validation, JWT verification, role/membership authorization, idempotency handling and service invocation. No ranking prompts or SQL in route functions.
- `domain/`: canonical request/read models, enums, pure policy types, transition guards and shared business invariants. No FastAPI, Celery, SQLAlchemy or network imports.
- `agents/intake/`: unstructured-text extraction, missing-field detection, normalization handoff, urgency and hard eligibility policy. It proposes data; a donor must confirm required fields.
- `agents/matching/`: PostGIS candidate queries through repositories, route estimates, constrained ranking, explanations and the distance-only strategy. It receives and revalidates eligible candidates, not arbitrary organizations.
- `agents/orchestrator/`: durable round/step management, dispatch, recovery leases, bounded retries and decline/no-driver/no-match behavior.
- `agents/reservation/`: accept/decline, capacity accounting, driver assignment, pickup and delivery transactions, notification requests.
- `db/`: mapped entities, repositories and transaction helpers. One SQLAlchemy `Base`; one Alembic history. No table creation at application import/startup.
- `integrations/`: bounded external calls and fake providers behind interfaces. No provider is allowed to mutate donation state or override rules.
- `apps/web/src/features/<role>/`: role routes, components and hooks. Cross-role components go in `components/`; HTTP/SSE wrappers go in `api/`; generated types must not be edited.

Avoid a general `utils.py` or `services.py` that absorbs every owner’s code. Add a named module where its responsibility is clear. Start with explicit functions and small services; do not introduce an agent framework unless an ADR explains a capability the current boundaries cannot provide.

## 4. Domain vocabulary and invariants

A **donation** is one indivisible listing in the MVP; a partial allocation is not supported. Quantity is kilograms, optional portions are a convenience, routes use meters/seconds, coordinates use named WGS84 latitude/longitude, timestamps carry offsets and persist as UTC `timestamptz`. Display time uses the location’s IANA timezone. Empty allergen lists mean a donor explicitly confirmed none; missing/unknown allergens require review. An LLM guessing “none” does not count as confirmation.

A **match** is an offer to one recipient in a particular matching round. A **reservation** is the recipient’s accepted hold on the entire donation. A **pickup assignment** is a driver’s task; declining that task normally reassigns a driver without releasing the recipient’s reservation. These are separate records and lifecycles.

Invariants enforced in database transactions:

1. At most one active offer per donation and at most one active reservation per donation.
2. At most one active assignment per donation. A driver’s conflicting time/capacity commitments cannot overlap.
3. Eligibility is checked before ranking and rechecked against current versions before reservation. A provider score cannot make an ineligible match valid.
4. Recipient capacity cannot become negative when two different donations are accepted concurrently.
5. Every aggregate write checks `version`; stale HTTP commands and stale worker results cannot overwrite new state.
6. Every successful state change appends history and outbox events in the **same** transaction. No committed change may rely solely on a Redis message for recovery.
7. Retries may redeliver tasks, but cannot duplicate a reservation, allocation, state-history transition or notification request.
8. No expired listing is matched or newly picked up. After collection, missed deadlines become handling exceptions (`failed` with a reason), not a re-match or an invisible disappearance.
9. A terminal donation cannot be reopened by a background retry. An operator creates a new confirmed listing if appropriate; the original history remains immutable.
10. Real credentials, precise locations and raw donor text are excluded from queue envelopes and routine logs.

See [data model](architecture/data-model.md) and [state transitions](architecture/state-machine.md) for implementation details.

## 5. End-to-end flow

### Describe and review

The donor requests an extraction draft. Intake returns proposed fields, field-level missing/uncertain reasons and provenance. Extracted text is untrusted data, not instructions to the system. Schema validation rejects invented enum values, unsafe timestamps and missing required information. The UI shows the proposed structured details and lets the donor correct them. Posting submits a complete `DonationInput`; it does not submit a model’s unreviewed response.

`POST /donations` authenticates the donor, determines the organization from membership, validates future timing using an injected clock, enforces the idempotency key and saves `submitted` plus its history/outbox row atomically. It returns 202 with the persisted ID, version and status. Workers do not run within the request or before the transaction commits.

### Validate and find an offer

The orchestrator requests intake/eligibility. Invalid or uncertain information becomes `needs_review`, not a guessed match. Confirmed food-safety/deadline failures are recorded with a reason. The rules engine filters food category, explicit allergens/dietary requirements, storage type/capacity, operating window, driver feasibility and route arrival before the safe deadline. Unknown safety-critical information is not eligible.

Matching searches within the configured geospatial radius, obtains bounded route estimates, checks feasible time windows with the handling buffer and ranks only surviving recipients. Scores and explanations record policy/config/model versions and feature values. A missing or unavailable routing service must not fabricate a road ETA. The result is an uncommitted proposal containing the input donation/profile versions and matching round.

The orchestrator accepts a result only if the current donation, round and versions still match. It rechecks time, saves one active offer and moves to `offered`, with expiry no later than the last feasible acceptance/pickup time. Notifications are separate outbox work. The match is not a reservation until the recipient accepts.

### Accept and reserve

The recipient accepts their active offer with an idempotency key and expected donation version. In one short transaction, the reservation service checks authorization, active offer, round, versions and expiry; rechecks policy and current available capacity; conditionally updates donation and capacity; inserts the active reservation; and writes history/outbox rows. Unique constraints backstop the conditional updates. A losing race returns 409 and refresh instructions.

No routing/LLM call is performed while holding database locks. Precomputed route information must be fresh enough for the policy, and feasibility must still hold at commit. A second recipient cannot be silently substituted inside the same acceptance command.

### Coordinate pickup

The reservation service selects a feasible available driver under the assignment transaction. Driver acceptance and pickup confirmation require that driver’s membership and matching assignment version. Driver decline/timeout releases that assignment and retries dispatch within the remaining safe window. If no feasible driver exists, the service releases capacity/reservation atomically and asks the orchestrator to re-match or end with a recorded reason.

Pickup records quantities/handling confirmation and marks `picked_up`; delivery completes the assignment and reservation, moves to `delivered`, and records impact once. Recipient capacity remains consumed until an explicit receiving-profile update reports newly available space; it is not automatically “freed” by delivering food into the recipient’s storage.

### Declines, cancellation and expiry

Decline/offer timeout excludes that recipient for the current listing, supersedes the offer and advances the matching round. An accepted reservation may be released before pickup with capacity credited exactly once. Donor cancellation after reservation requires the same release/notification transaction; after pickup it is not a normal cancellation. Expiry and release jobs are database-backed scheduler work, not long Celery countdowns. Terminal reasons distinguish no recipients, no driver, deadline reached and technical failure.

## 6. Eligibility, urgency and ranking

Hard constraints are owned by Mokshith, with routing/data input from Rushitha. Eligibility returns structured pass/fail reason codes and the policy version. Use one shared policy entry point for both algorithms, and recheck mutable inputs at acceptance.

Urgency sorts **donations awaiting processing** by remaining feasible pickup slack. Adding the same donation-wide urgency constant to every recipient’s score does not change recipient ranking. If urgency contributes to ranking, use a candidate-specific slack/risk feature based on that route and recipient window, and document the formula. A predictive spoilage estimate can prioritize processing; it must never extend the donor-confirmed safe-use deadline.

Multi-criteria ranking uses normalized [0,1] features with documented direction and weights. Required dietary constraints stay hard constraints; only extra preferences may be a soft fit. Capacity fit considers current available capacity, not maximum nominal capacity. Fairness uses the same eligible cohort/window and historical allocated kilograms, not the raw number of accounts. Record the component features and deterministic tie-break `(score DESC, travel_time_s ASC, recipient_id ASC)`. A constrained model may score/reorder only provided eligible IDs. Invalid model output is rejected and may use an explicitly logged deterministic fallback.

`config/matching.json` contains design defaults, not measured optimum values. The owner must validate weight sum, bounds and version before using them. Distance-only applies the same hard constraints and route inputs, then chooses shortest distance with stable ID tie-breaks. It does not receive an easier safety filter or share mutable reservation state with the AI experiment.

## 7. Contracts and integration discipline

[Canonical Python wire models](../backend/src/foodbridge/domain/contracts.py) generate [JSON Schema](../contracts/domain.schema.json) and [TypeScript](../apps/web/src/api/generated/domain.ts). Generated files are checked into Git so frontend work can proceed without Python. Run `make contracts` after changing models; `make check` detects drift. ORM entities are separate persistence types and must be mapped deliberately.

The exported [OpenAPI](../contracts/openapi.json) describes only routes actually mounted by FastAPI. Planned business endpoints are specified in [api.md](architecture/api.md), not advertised as working endpoints. When implementing each route, add response/request models and regenerate OpenAPI in that PR.

Breaking field/status changes require a consumer-first plan: add the compatible field, update consumers, migrate stored data, then remove the old field in a versioned change. Do not rename shared fields in a feature branch without coordinating affected owners. Event types carry `.v1`, and consumers reject unsupported major versions.

## 8. Authentication and data access

Use JWT access tokens issued by a configured OIDC provider; verify signature, issuer, audience and expiration using cached JWKS. Do not invent a custom password system for the demo. Map `sub` to a server-managed user and explicit organization memberships. Roles are donor, recipient, driver and operator; the UI role switcher in the scaffold is navigation, not authorization.

Donors see their own donations; recipients see their own offers/reservations; drivers see assigned pickups; operators see scoped operational data. Membership and resource ownership are checked on every command, detail/list endpoint and SSE connection/replay. Never accept actor/organization IDs from a browser body as authority. Seeded demo identities must use the same authorization layer.

Fetch-based SSE sends the bearer header. Tokens are kept in memory; do not put tokens in stream URLs or localStorage. Add CORS origins/methods deliberately as authenticated routes arrive. Health endpoints are public and reveal no credentials or dependency exceptions. No business endpoints should be exposed before their authorization tests pass.

## 9. Reliability and observable behavior

Delivery is at least once, not exactly once. The planned transactional outbox and consumer receipts make effects idempotent. Every business task has a durable lease, bounded retry budget, attempt history and explicit outcome. A retry reuses the same effect identity; it does not create a new donation. Stale results are ignored with a log reason. A poisoned task goes to persistent failure records after the budget and requires operator replay with precondition checks. [events.md](architecture/events.md) defines this precisely.

Record request/correlation/event IDs, aggregate version, matching round, agent, algorithm/config version, queue wait, provider latency and outcome reason. Log no access tokens, raw prompts, address-bearing payloads or provider secrets. Metrics include P50/P95 decision latency, throughput, offer acceptance, pickup completion, constraint violations, expired/no-match reasons, retries and dead letters. A healthy API process is distinct from ready infrastructure and from functioning workers.

The application UI distinguishes waiting, needs review, offer expired, conflict, re-matching and retryable failure. It reads authoritative snapshots after reconnect or 409. It does not optimistically claim a successful reservation before the server confirms it.

## 10. Build order and release gates

First land contracts and the database foundation. Then ship one authenticated donation-to-offer vertical slice with deterministic fake providers. Add transactional acceptance and driver pickup, then recovery/SSE, then live adapters and evaluation. Detailed tasks and owners are in the [implementation plan](team/implementation-plan.md). Each part has runnable tests and a sample handoff artifact before another owner depends on it.

The MVP is ready only when the workbook’s AT-1 through AT-7 pass on real PostgreSQL/PostGIS and Redis, the browser workflow succeeds with configured demo identities, failure injection preserves state, and both algorithms have reproducible measured results. A mockup, task registration or passing health check is not this milestone.

## 11. Known decisions still requiring implementation evidence

- Select the OIDC provider and provision demo identities before implementing protected routes.
- Select extraction/ranking model and prompt versions; evaluate them on held-out synthetic descriptions. No provider key is required for foundation tests.
- Agree food-handling policy with the project’s academic scope; do not treat predictive scores as food-safety certification.
- Build recipient capacity/dietary-profile editing and the receiving-window timezone conversion before claiming operational eligibility.
- Choose a shared demo host only after local acceptance gates; record actual URL/TLS/backup procedure in deployment docs.
- Validate map provider/license and OSRM coverage. Straight-line estimates may support candidate search, not guaranteed pickup feasibility.

These are assigned tasks, not reasons for different owners to invent incompatible implementations. Change a decision through an ADR and update the consuming contracts together.
