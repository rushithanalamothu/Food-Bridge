# Testing and evaluation

## Foundation coverage

`make check` verifies contracts, legal status edges, worker registration/routing, API health semantics, frontend health-response validation, static types, frontend build, formatting, generated-artifact drift, documentation links and Compose syntax. The infrastructure integration test checks real PostGIS/Redis and the migration head. These are foundation tests only.

Add a test when it protects behavior or an integration invariant, not just to mirror a directory or trivial component. Use an injected clock, ID generator and fake provider responses for deterministic unit tests. Domain tests must run without network credentials. Geospatial queries, partial uniqueness, transaction races and outbox correctness require real PostgreSQL/PostGIS; never infer correctness from SQLite or in-memory dictionaries.

## Feature acceptance suite

| Workbook test | Required evidence | Lead |
| --- | --- | --- |
| AT-1 valid donation | One eligible offered recipient with stored features/explanation, state/history evidence | Rushitha + Mokshith |
| AT-2 ineligible recipient | Dietary, capacity, storage, hours and deadline violations excluded before ranking and rechecked at reserve | Mokshith |
| AT-3 simultaneous acceptance | Two separate DB connections race on one donation; exactly one reservation; losing response 409 | Tej |
| AT-4 decline/re-match | Offer superseded, recipient excluded, round incremented, next valid offer or safe terminal outcome | Tej + Rushitha |
| AT-5 worker failure | Kill worker at defined commit/publish points; no lost listing/duplicate effects; recovery within measured budget | Tej |
| AT-6 routing outage | Bounded retry/real configured fallback or explicit safe failure; no fake feasibility | Rushitha |
| AT-7 deadline/no candidate | Explicit terminal status/reason; no forced match or late pickup | Mokshith + Tej |

Additional required races: two donations compete for one recipient’s limited capacity; accept versus offer-expiry; cancel versus pickup confirmation; old worker result versus newer matching round; duplicate delivery confirmation; driver overlapping assignments. Test cross-organization detail/list/SSE access, invalid token issuer/audience/expiry, prompt injection and model-selected unknown/ineligible IDs.

## Evaluation protocol

The workbook generator’s scale is 10 donors, 6 receivers, 5 drivers and 20 donations; the scaffold generates that file shape deterministically. It is a smoke dataset, not sufficient experimental evidence. Add fixed regression scenarios for near deadline, exact/insufficient capacity, storage mismatch, dietary mismatch, no driver, route outage, stale round, concurrent reservation and sustained burst arrivals. A reviewed scenario manifest records intended outcomes without embedding the algorithm’s answer into the inputs.

Freeze seed, base clock, dataset hash, policy/config versions, model/provider/prompt version, route source/cache, build SHA, workload arrival schedule, simulated outcomes and hardware. Run algorithms in independent database/state snapshots; neither consumes the other’s capacity/history. Use the same hard-policy gates and route data. Warm/cold model/cache runs are reported separately. Do not pick a favorable seed after seeing the result.

Metrics and denominators:

- Decision latency: request persisted (`submitted`) to offer committed. Record extraction review separately and report P50/P95, queue wait and inference time. Report failed/time-out attempts separately rather than dropping them silently.
- Successful pickup rate: picked-up donations divided by the fixed scenario’s eligible attempts under a strategy-independent, documented eligibility definition. Also report all submitted attempts, exclusions, no matches and expiries. Document simulated completion assumptions.
- Completion rate: delivered / reserved, alongside picked-up / reserved, so these are not confused.
- Constraint violations: count and rate, target zero; failures remain visible even if aggregate completion improves.
- Double booking: donations with >1 committed active reservation or duplicated fulfilled allocation, target zero. Check capacity over-allocation separately.
- Fairness: allocation kilograms and counts per recipient within comparable eligibility cohorts/time windows; report Jain’s index `sum(x)^2 / (n*sum(x^2))` with its eligible cohort and define all-zero as not applicable. Fairness without recipient eligibility/capacity context can mislead.
- Throughput and recovery: completed decisions per second, queue/lease lag, retries, dead letters, lost/duplicate listings and time to recovery after injected failures.

Store results under ignored `evaluation/results/<run-id>/` with a manifest and raw records. Commit a reviewed summary with reproducible commands and source artifacts when measurements exist. Mockup values (including the old 88/100 comparison) are illustrative and cannot be copied into the research report as results.
