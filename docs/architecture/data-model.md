# Persistence model and transaction rules

Status: the intake migration implements users/organizations/memberships, drafts, donations, history, idempotency, outbox and intake evaluations. [The feature runbook](../features/intake.md) describes the concrete model. Recipient/capacity, matches, reservation, assignment, generic workflow recovery and stream tables below remain the schema plan. Rushitha owns the schema history; the business owner reviews each table/transaction affecting their module.

## Common rules

- App-generated UUID primary keys; immutable `created_at`, UTC `timestamptz` dates; mutable aggregates carry integer `version >= 1`. Enum values match canonical wire types; choose text + named CHECK constraints to make migrations explicit.
- Named foreign keys, CHECK constraints and indexes use `foodbridge.db.Base` naming rules. Units appear in column names. Location uses `geography(Point,4326)` with a GiST index, created with longitude first; wire models use named latitude/longitude.
- Store positive quantity as `numeric(12,3)` and enforce bounds at the database. Wire JSON is a number; compare using decimal arithmetic in allocation transactions. Reject values that round to zero.
- The same physical database serves all workers. Table access goes through shared repositories/services; an agent’s own transaction must not directly rewrite another agent’s ownership fields.
- No database business data at import time, no `create_all` in startup, no Redis locks as the source of reservation truth. No SQLite replacement for geospatial/concurrency tests.

## Tables and owners

| Table | Important fields / constraints | Domain owner |
| --- | --- | --- |
| `users` | id, OIDC subject unique, display name, active | Tej |
| `organizations` | id, name, location, timezone, active, verified eligibility marker | Rushitha |
| `memberships` | user + org + role unique; server-managed | Tej |
| `recipient_profiles` | org unique, accepted categories/storage, dietary rules, receiving windows, version | Rushitha + Mokshith |
| `recipient_capacity` | recipient + storage unique, reported_free_kg, committed_inbound_kg, version; net available >= 0 | Rushitha + Tej |
| `drivers` | user unique, available window, vehicle kg capacity, allowed storage, version | Tej |
| `donation_drafts` | donor org, raw text, proposed fields, missing fields, provenance, version, status | Mokshith |
| `donations` | donor org, confirmed fields, pickup/safe-use times, status, version, matching_round | Mokshith + Tej |
| `eligibility_results` | donation + round + recipient + policy version, pass/fail, reason codes, input versions | Mokshith |
| `matches` | donation, recipient, round, input versions, route/features, config/model versions, status, expiry | Rushitha |
| `reservations` | donation, match, recipient, allocated_kg/storage, status, released_at, version | Tej |
| `pickup_assignments` | donation, reservation, driver, time window, status, version | Tej |
| `status_history` | donation, previous/next status, version, actor, reason, correlation ID, timestamp | Tej |
| `outbox_events` | UUID event ID, aggregate/version, event type, payload, publish lease, attempt count, published_at | Tej |
| `consumer_receipts` | consumer + event/effect ID unique; completion and lease metadata | Tej |
| `workflow_steps` | donation + round + step unique; input version, lease, deadline, attempts, outcome | Tej |
| `task_failures` | task/effect identity, sanitized error, attempts, terminal reason, replay audit | Tej |
| `notifications` | notification effect key unique, template, target ID, status, provider ID | Tej |
| `idempotency_records` | actor + method + normalized route + key unique; request hash, saved response, expiry | Tej |
| `stream_events` | safe ordered cursor, event ID unique, audience, event envelope, published_at | Tej |
| `evaluation_runs` | algorithm, seed, base clock, data/config/policy/model hashes, result location, synthetic=true | Rushitha |

Suggested partial unique indexes: one `matches(donation_id) WHERE status='offered'`; one `reservations(donation_id) WHERE status='active'`; one `pickup_assignments(donation_id)` for assigned/accepted/collected statuses. Require `status_history(donation_id,aggregate_version)` unique and unique outbox effect `(aggregate_id,aggregate_version,event_type)`. Foreign key relationships must prevent a reservation using a match for a different donation or recipient; use composite FK/unique pairs or equivalent transactional validation plus tests.

Preserve old offers/steps/history; never delete rows to “fix” a re-match. Draft raw text and model output are private data with bounded retention, not general log/event material. The draft-to-donation link preserves provenance without making private extraction payloads public.

## Reservation and capacity transaction

Optimistic concurrency is the public contract, backed by database conditional updates and uniqueness. Typical implementation:

1. Determine actor membership from verified identity. Read the offered match and prepared eligibility/route inputs before opening a write transaction.
2. In the transaction, check the request idempotency record, current offer/round/deadline and expected aggregate version.
3. Acquire/check capacity rows in a fixed order (recipient ID, storage). Conditionally increment `committed_inbound_kg` only when `reported_free_kg - committed_inbound_kg >= donation.quantity_kg`, checking the expected profile/capacity version. Recheck eligibility against current values.
4. Conditional donation update `WHERE id=:id AND version=:expected AND status='offered'`, increment version; close the active offer.
5. Insert active reservation and allocation. Write history, notifications/outbox and idempotency response; commit together.
6. If any affected-row count or unique condition fails, rollback the **whole** transaction and return 409. Do not leave capacity deducted after a failed donation update.

No network/provider calls inside locks. Serialize contested rows consistently and retry serialization/deadlock errors a small bounded number of times without duplicating effects. Competing reservations on two different donations for the same recipient must be tested; a per-donation lock alone cannot prevent over-allocation.

Capacity is accounted **per storage type**, not as one pooled number. A chilled donation cannot use ambient shelf capacity. Each capacity row stores `reported_free_kg` (physical free space after the last report/delivery adjustments) and `committed_inbound_kg` (reserved food not yet delivered). Both are nonnegative; `available_kg = reported_free_kg - committed_inbound_kg >= 0`. The wire profile exposes `available_capacity_kg_by_storage` derived from this accounting.

Reserve increments inbound; release before collection decrements inbound once. Delivery decrements both inbound and reported free space by the recorded allocation in the same transaction, so net available stays the same as food moves into storage. A later receiving-profile command reports updated physical free space; it leaves outstanding inbound commitments intact, uses a version check, and rejects a reported value below current commitments with a capacity-conflict reason requiring explicit resolution. Never overwrite the inbound counter with a browser value. Observed quantity discrepancies require an explicit reviewed adjustment, not an implicit credit that makes storage look empty.

## Offer and assignment transactions

Offer creation CAS-checks donation version/round, verifies fresh eligibility versions/deadline, supersedes prior offer and inserts one active offer atomically. A stale worker result must not reopen an offer or replace a reservation.

Assignment acceptance must prevent a driver from accepting conflicting jobs. Use a DB overlap constraint for accepted time ranges, or serialize the driver row and check commitments inside the same transaction. All recipients/driver windows and storage capacity must remain feasible; simply storing a `driver_id` on a donation is insufficient.

Driver decline releases assignment only; recipient release/cancellation releases the reservation and capacity too. After pickup, failure records a handling exception and human follow-up; it does not offer collected food to another recipient.

## Migration workflow

Run from repository root:

```sh
uv run alembic -c backend/alembic.ini revision --autogenerate -m "add donation model"
uv run alembic -c backend/alembic.ini upgrade head
uv run alembic -c backend/alembic.ini check
```

Import all mapped entities into the migration metadata registry; otherwise autogenerate cannot see them. Review generated SQL and constraints manually; migrations are not an approval substitute. The scaffold excludes PostGIS-owned reference tables from application autogeneration.

One person, normally Rushitha, coordinates the next revision when parallel branches touch migrations. Rebase before creating the revision. Do not renumber or rewrite merged revisions; resolve multiple heads with a reviewed merge migration where needed. CI must upgrade an empty database and run `alembic check`. Downgrade is tested where safe; the extension-only first revision deliberately leaves a potentially pre-existing PostGIS extension intact. Never drop volumes as a routine way to make a migration pass.
