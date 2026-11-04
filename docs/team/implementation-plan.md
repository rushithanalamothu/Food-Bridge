# Implementation plan and acceptance gates

This is a dependency-ordered backlog, not a claim that the product is complete. The foundation, intake and Tej's backend workflow are implemented. Live matching/data services and complete client integration remain pending. Dates should be assigned by the team; do not invent delivery commitments.

## Implemented Tej workflow

[Workflow implementation and verification](../features/workflow.md) covers O01/O02, R01–R03, sandbox N01, backend O03 and supporting F02/F04 storage/contracts. Tests exercise Workbook AT-1–7 with explicit synthetic/failure adapters on real PostgreSQL/PostGIS, plus a real HTTP/broker/worker delivery smoke. These tests do not certify Rushitha's live M01–M03 implementation, Mithil's W02–W04 screens or shared-cloud promotion. F03 now resolves all active role memberships; identity-provider selection/provisioning and browser login remain pending. Shared storage, contracts and the additive lifecycle edge need affected-owner review before merge. The phase tables below retain the dependency/acceptance checklist.

## Implemented intake slice

Mokshith's I01/I02 logic, draft/submission contracts, donor review UI and intake worker/relay are implemented. Tej adds recipient/capacity/offer/reservation/assignment support without replacing those tables or the intake policy. F01's live data/profile repositories and V01's live matching integration remain pending. See [feature details](../features/intake.md) before extending shared tables.

## Intake v0.3 alignment

Mokshith's intake-owned alignment adds spec urgency defaults, optional packaging, configurable review policy, source-backed quantity normalization, one transient model retry, diagnostics and a typed internal handoff. See [requirements and acceptance evidence](../specs/intake-v0.3-alignment.md). Tej now consumes submission/result events and wires the backend workflow; Rushitha must provide live candidate/route facts and matching. FT-07/full V01 has synthetic integration coverage; live integration remains pending. Protected deployment-wide metrics collection remains pending.

## Shared AI integration rule

The app-wide provider client is implemented for intake. Future M03 ranking and any other model-backed feature must reuse `integrations.ai.generate_structured` and `Settings.ai_*`; they must not add their own provider/key/model settings. Configure the key once using [shared AI setup](../setup.md#shared-ai-configuration). Prompts/output types remain feature-specific, and model output must still pass domain constraints. This does not mark matching/ranking or the full donation pipeline implemented.

## Phase 0 — Shared foundation (initial scaffold)

Delivered: repository layout, local configuration, locked dependencies, API health, role app shell, worker queues/probes, PostGIS migration entry point, canonical initial DTOs, legal state edges, synthetic file generator, tests/CI, ownership and design documents. The historical HTML prototype is saved as a design reference.

Not delivered: the business tables or authenticated donation workflow. Foundation checks do not satisfy workbook AT-1–7.

## Phase 1 — Contract and storage integration

| ID | Owner | Task | Acceptance | Dependency |
| --- | --- | --- | --- | --- |
| F01 | Rushitha + Mokshith | Add organizations, donation/draft, recipient profile/capacity model and migration | Empty PostGIS DB migrates; FKs/CHECKs and indexes tested; downgrade policy documented | Foundation |
| F02 | Tej + Rushitha | Add user/membership, offer/reservation/assignment, outbox/history/receipt/step tables | Transaction constraints reviewed; one Alembic head | F01 contract review |
| F03 | Tej + Mithil | Select OIDC provider, add token verification and `/me` contract | Issuer/audience/expiry and cross-org negative tests; seeded demo identities | Foundation |
| F04 | All owners | Add draft, match-status, reservation, assignment and SSE payload DTOs/examples | Consumer review; `make contracts` + drift check pass | Foundation |
| F05 | Rushitha | Add safe fixture loader for implemented entities | Deterministic IDs, FK integrity, explicit dev-only opt-in; no truncation | F01, F02 |

**Gate:** one team member can apply all migrations, load the scenario and read authorized entities without another person’s local files.

## Phase 2 — First vertical slice: confirmed donation to offer

| ID | Owner | Task | Acceptance | Dependency |
| --- | --- | --- | --- | --- |
| I01 | Mokshith | Extraction draft + donor-review policy | Missing allergens/deadlines remain unknown; invalid/low-confidence data requires review | F04 |
| I02 | Mokshith | Shared eligibility and urgency rules | Dietary, storage, capacity, hours, safe-use and route infeasibility tests; versioned reason codes | F01, F04 |
| M01 | Rushitha | PostGIS nearby search + routing adapter/fake | Named units; route timeout/unavailable behavior; search radius uses geography meters | F01 |
| M02 | Rushitha | Distance-only matcher | Same hard policy; stable tie-break; no eligible recipient outcome | I02, M01 |
| O01 | Tej | Durable submission/outbox relay, workflow steps, CAS result application | Broker outage and duplicate delivery tests; event survives API commit | F02, F03, F04 |
| W01 | Mithil | Donor form/review/error/status screens | Works against fixtures, keyboard/mobile usable; confirmation sends typed fields | F04 |
| V01 | Mokshith + Tej + Mithil | Connect POST donation → eligibility → deterministic offer → UI | Valid user flow on real DB/Redis; invalid data never offered | All above |

**Gate:** one synthetic donor posts a confirmed donation and one authorized recipient can read a feasible offer. Model ranking can still use a deterministic fake provider. No reservation “success” is shown yet.

## Phase 3 — Reservation and pickup

| ID | Owner | Task | Acceptance | Dependency |
| --- | --- | --- | --- | --- |
| R01 | Tej + Rushitha | Transactional accept/decline/release | Concurrent same-donation race: exactly one success; shared-recipient capacity cannot overbook | F02, V01 |
| R02 | Tej | Driver availability/assignment/accept/decline | One feasible assignment; no overlapping accepted commitments; decline keeps recipient hold if feasible | R01 |
| R03 | Tej | Pickup/delivery commands | Authorized assigned driver only; deadlines/versions checked; impact exactly once | R02 |
| W02 | Mithil | Recipient profile and offer screens | Correct conflict/expiry/decline handling and fresh snapshot after 409 | F04, R01 |
| W03 | Mithil | Driver screens | Clear handling/pickup notes and explicit server-confirmed states | R02, R03 |
| N01 | Tej | Notification adapter/outbox | Sandbox only; stable effect key; retries and potential duplicates documented | O01 |

**Gate:** full donor → recipient acceptance → driver pickup → delivery scenario passes, with two-reservation concurrency test and correct capacity release accounting.

## Phase 4 — Recovery, live status and operations

| ID | Owner | Task | Acceptance | Dependency |
| --- | --- | --- | --- | --- |
| O02 | Tej | Deadline sweeper, worker leases, retries, failures/replay | Duplicate, stale-result, killed-worker, broker-outage and poison-input tests | O01, R01 |
| O03 | Tej + Rushitha | Ordered, audience-scoped SSE persistence/replay | Concurrent commit ordering, token scope, reconnect/cursor-expiry tests | F02, O02 |
| W04 | Mithil | SSE UI integration and operations board | Snapshot/stream race handled; no duplicate impact increments; disconnected state visible | O03 |
| M03 | Rushitha + Mokshith | Multi-criteria ranking + normalization/model adapters | Model cannot select an ineligible ID; prompt/schema/provider versions recorded | M02, I02 |
| AT | Tej, each owner supports | Workbook acceptance scenarios AT-1–7 | All pass on real PostgreSQL/PostGIS + Redis | Phases 2–4 |

**Gate:** failure injection recovers without lost/duplicate listings and without constraint violations. UI displays re-match and error states honestly.

## Phase 5 — Evaluation and demo readiness

Rushitha runs independent scenario replays for distance-only and multi-criteria strategies. Mokshith validates policy/urgency and held-out descriptions. Tej verifies concurrent load/recovery and deployment rollback. Mithil verifies complete browser workflows, accessibility and usable status language.

**Gate:** publish dataset/config/model hashes and measured metrics; no AI improvement claim from invented mock figures. Shared demo passes an authenticated smoke scenario with sandbox notifications, TLS, migrated database, stable build SHA and a tested restore/rollback procedure.

## Known first-PR coordination points

F01/F02 table design and F04 DTO additions are the most likely collision areas. Agree column/command shapes in an issue or draft PR before writing both independently. Rushitha coordinates migration numbering; Tej integrates shared lifecycle changes; Mithil owns router/global style changes. Feature owners can still write their own modules/tests while these PRs are in review.
