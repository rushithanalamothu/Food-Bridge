# HTTP and browser-status contract

Status: health and donor intake routes are implemented; other v1 routes are planned. [The intake feature contract](../features/intake.md) specifies the implemented request/response shapes and local demo boundary. The running `/docs` and [generated OpenAPI](../../contracts/openapi.json) are authoritative for implemented routes. A planned route below must not return fabricated successful data while it is unfinished.

## Conventions

- Base path `/api/v1`; JSON field names are `snake_case`, including in TypeScript wire types.
- IDs are UUID strings, timestamps RFC3339 with timezone, quantity kilograms, distance meters, duration seconds. Display conversions are frontend concerns.
- Bearer JWT auth on all business routes; role **and resource membership** checked on every access. The organization and actor come from verified server-side membership.
- Commands use `Idempotency-Key: <UUID>` and include the affected aggregate’s `expected_*_version` when updating existing state. Do not use `PUT status` or a browser-provided destination status.
- Store idempotency by `(actor_id, HTTP method, normalized route, key)`, request-body hash and original HTTP response. Same key/body returns the original response; same key/different body returns 409 `idempotency_key_reused`. Retain records at least 7 days in the MVP; expiry behavior must be documented before shortening this.
- Lists use `limit` (default 25, max 100) and opaque cursor `(created_at,id)` for stable ordering, returning `{items,next_cursor}`. Filtering never changes authorization scope.
- 400 invalid command; 401 invalid/missing token; 403 actor lacks required role; 404 missing/inaccessible resource; 409 stale version/state, offer expiry or capacity conflict; 422 field validation; 429 admission/rate limit; 503 unavailable required dependency. Never return 200 for a failed reservation.
- Business errors use canonical `ApiError`: `code`, human-readable `message`, server `request_id`, structured `details`. Intake routes use canonical `ApiError`, including sanitized 422 field details and a server request ID.
- Future-dated pickup/deadline checks use an injected server clock. The schema enforces ordering/offsets; it does not assert that a fixed fixture date is currently in the future.

## Endpoint inventory

| Method and route | Role | Meaning / response | Status |
| --- | --- | --- | --- |
| GET `/health/live` | Public | 200 `LiveStatus`; no external I/O | Implemented |
| GET `/health/ready` | Public | 200 or 503 `ReadyStatus`; actual PostGIS + Redis probes | Implemented |
| GET `/me` | Donor | Active donor identity/membership and pickup site | Implemented donor membership; gateway login pending |
| POST `/donation-drafts` | Donor | 201 completed `DraftRead`; bounded extraction before review | Implemented |
| GET `/donation-drafts/{id}` | Owner donor | Proposed fields, uncertainties, provenance and status | Implemented |
| POST `/donations` | Donor | `DonationSubmit` with draft/version + confirmed fields; 202 `IntakeDonationRead` | Implemented |
| GET `/donations` | Authenticated | Scoped cursor list; donor role implemented | Implemented for donors |
| GET `/donations/{id}` | Resource member | Donor snapshot, version and urgency | Implemented for donors |
| POST `/donations/{id}/confirm-details` | Owner donor | Correct `needs_review` listing; versioned, 202 | Planned, Mokshith |
| POST `/donations/{id}/cancel` | Owner donor/operator | Versioned pre-pickup cancellation; 200 snapshot | Planned, Tej |
| GET `/recipient-profile` | Recipient | Own location, categories, capacity and hours | Planned, Rushitha |
| PUT `/recipient-profile` | Recipient | Versioned profile update; 200 profile | Planned, Rushitha |
| GET `/matches` | Recipient | Own active and past offers, scoped cursor list | Planned, Rushitha |
| GET `/matches/{id}` | Resource member | `MatchRecommendation` plus offer status | Planned, Rushitha |
| POST `/reservations` | Recipient | `ReservationRequest`; 201 reservation + donation version | Planned, Tej |
| POST `/matches/{id}/decline` | Offered recipient | Version, optional reason; 200 decision, re-match asynchronous | Planned, Tej |
| POST `/reservations/{id}/release` | Reserving recipient/operator | Versioned pre-pickup release; 200 snapshot | Planned, Tej |
| GET `/pickups` | Driver | Assigned/accepted tasks; scoped cursor list | Planned, Tej |
| POST `/pickups/{id}/accept` | Assigned driver | Assignment version; 200 assignment | Planned, Tej |
| POST `/pickups/{id}/decline` | Assigned driver | Version/reason; 200 decision; redispatch asynchronously | Planned, Tej |
| POST `/pickups/{id}/confirm-pickup` | Accepted driver | Version, handling confirmation, observed amount | Planned, Tej |
| POST `/pickups/{id}/confirm-delivery` | Accepted driver | Version, delivery confirmation; 200 snapshot | Planned, Tej |
| GET `/operations/summary` | Operator | Counts, time window, units and measured/synthetic indicator | Planned, Tej + Rushitha |
| GET `/operations/failures` | Operator | Persisted failures and replay eligibility | Planned, Tej |
| POST `/operations/failures/{id}/replay` | Operator | Audited replay, current preconditions, 202 | Planned, Tej |
| POST `/donations/{id}/demo-eligibility` | Local demo donor | 202 evaluation job using server-owned synthetic facts | Implemented, local demo only |
| GET `/intake/evaluations/{id}` | Owner donor | Pending/completed/stale/failed eligibility result | Implemented |
| GET `/events` | Authenticated | Authorized fetch-SSE stream with durable replay | Planned, Tej + Mithil |

The intake slice also exports `DraftCreate`, `DraftRead`, `DonationSubmit`, `IntakeDonationRead`, `DonorIdentity`, typed eligibility inputs/results and `EvaluationRead`. See its generated schema and runbook for implemented shapes. Remaining draft revision, match/pickup and stream interfaces still require consumer review.

`DonationInput`, `DonationRead`, `RecipientProfile`, `MatchRecommendation`, `ReservationRequest`, `EventEnvelope` and `ApiError` remain the original foundation types. Reservation/assignment responses, remaining command bodies and stream payloads need additive Pydantic definitions in the implementing owner’s contract PR **before** consumers build against them. The endpoint table fixes responsibility and intent, not invented response fields.

A draft extraction request must never be accepted as `DonationInput`. The draft route uses its own text/location schema; missing values remain missing, and model output carries field provenance. Profile capacity editing requires `expected_profile_version` alongside the new profile snapshot. Preserve the public `RecipientProfile.version` to coordinate reservation checks.

## Reservation request example

```http
POST /api/v1/reservations
Authorization: Bearer <access-token>
Idempotency-Key: <uuid>
Content-Type: application/json

{"match_id":"<uuid>","expected_donation_version":4}
```

A successful response describes a committed reservation; sending a queue message alone is not success. If another operation changed version 4, return 409 `stale_version` and let the client refetch. If an idempotent retry repeats a successful command, return its original response even if a new request would no longer be allowed. The DB transaction, not a UI disable state, prevents double booking.

## SSE implementation contract

Use `fetch` streaming so the browser can send `Authorization` and `Last-Event-ID`; native `EventSource` does not support an arbitrary bearer header. Prefer one stream per logged-in browser context, scoped to the user’s accessible organizations/tasks. Send `Content-Type: text/event-stream`, disable proxy buffering, and do not cache.

The wire `id` is a durable, increasing **stream sequence**, distinct from the UUID `event_id`. Payload uses `EventEnvelope`; its type remains versioned. Keepalive comments every 15 seconds are not business events. Persist authorized replayable events for at least 7 days; if a cursor is outside retention return a structured 409 `stream_cursor_expired` before starting the stream. The client refetches snapshots and reconnects without a cursor.

To avoid the snapshot/subscribe race, establish the stream, buffer events, fetch snapshots, then apply only events newer than each snapshot’s aggregate version. Gaps trigger a snapshot refetch. Ignore duplicate sequence/event IDs; never blindly increment UI counters from duplicated events. On reconnect send the last applied stream sequence, use bounded backoff (1–30 seconds with jitter), and show a reconnecting state. Refresh tokens through the auth adapter before reconnecting.

The stream publisher is a single elected writer enforced by a PostgreSQL transaction-scoped advisory lock, not merely “one process” in a deployment manifest. It reads committed, not-yet-streamed outbox rows, inserts `stream_events` with sequence IDs, and marks those rows streamed in one short transaction while holding that lock. The next publisher cannot allocate/publish a later cursor until the transaction commits or rolls back. API instances read only committed stream rows in sequence order; Redis notifications only wake readers. Publish order is the stream’s order, and clients still use aggregate versions to reconcile snapshots.

A PostgreSQL sequence allocated by unrelated business transactions before commit would not guarantee commit order and must not be used as the replay cursor. Keep broker publication and stream-publication markers separate on the outbox, and test two concurrent business commits plus publisher crash/restart so neither destination can be skipped accidentally.

Cancellation, capacity conflicts, offer expiry and reassignment all generate status events. Exact event payloads that the UI uses must be included in the owner’s contract/examples PR. Polling scoped snapshots every 15 seconds is the temporary fallback if SSE is unavailable; it must not display “live” while disconnected.

## Intake v0.3 additive contracts

`GET /api/v1/intake/policy` requires the current donor identity and returns `IntakePolicy` (generated schema). Donor clients use its configurable description limit and extra required review fields. `packaging_type` is optional on proposals and confirmed donations. Evaluation results now distinguish donation-level decision/reasons from candidate eligibility and aggregate state. `IntakeHandoff` is an internal service read model, not an HTTP or queue endpoint. Local-only opt-in `/api/v1/metrics` is excluded from OpenAPI and exports process-local non-PII metrics. See [spec amendments and remaining dispatch](../specs/intake-v0.3-alignment.md).
