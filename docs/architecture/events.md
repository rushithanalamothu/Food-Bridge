# Events, worker boundaries and failure recovery

Status: implementation contract. The scaffold configures queues and diagnostic tasks only. Durable outbox/receipts, recovery scheduling and business handlers are the orchestrator/reservation workstream’s next tasks.

## Queue ownership

| Queue | Consumer | Commands handled | Results returned through persisted events |
| --- | --- | --- | --- |
| `orchestrator` | Tej’s orchestrator | Start/continue workflow, process outcomes, re-match, recover lease | Next step or recorded terminal outcome |
| `intake` | Mokshith’s intake agent | Extract draft, validate confirmed donation, evaluate eligibility | Draft reviewed/needs-review, eligibility ready/blocked |
| `matching` | Rushitha’s matching agent | Search/route/rank provided donation round | Match proposed or no eligible candidate |
| `reservation` | Tej’s reservation/pickup agent | Coordinate assignment, expiry/release, notifications | Assignment/notification outcomes |

HTTP reservation/acceptance commands commit the locking transaction synchronously. They are not “accepted” just because a queue task was enqueued. Workers handle asynchronous coordination around the committed result. The orchestrator does not synchronously wait for a child Celery task; it advances from durable events.

Python task names use `foodbridge.<agent>.<verb>`. Current `probe` tasks are diagnostics only. Do not call another agent’s handler directly or copy its logic. Queue messages contain a canonical `EventEnvelope` or a versioned typed command with the same metadata, and IDs of committed records. Re-fetch state before producing effects.

## Event shape

[Example envelope](../../contracts/examples/event.json): UUID event ID, `.v1` event type, schema version, aggregate UUID/version, correlation UUID, occurred-at timestamp, minimal payload. Domain payload definitions are additive contract work; a loose envelope dictionary is not permission to send arbitrary JSON.

Initial vocabulary to implement:

- `donation.submitted.v1`, `donation.review_required.v1`, `donation.eligible.v1`.
- `matching.proposed.v1`, `matching.exhausted.v1`, `matching.requested.v1`.
- `match.offered.v1`, `match.declined.v1`, `match.expired.v1`.
- `reservation.created.v1`, `reservation.released.v1`.
- `pickup.assigned.v1`, `pickup.assignment_released.v1`, `pickup.collected.v1`, `pickup.delivered.v1`.
- `donation.cancelled.v1`, `donation.expired.v1`, `workflow.failed.v1`.
- `notification.requested.v1`, `notification.sent.v1`, `notification.failed.v1`.

Events are immutable statements after a committed change. Commands request work and can be rejected. Store result provenance and reasons in the database; queue payloads carry IDs/rounds, not raw food text, full model prompts or addresses. Route provider input privately through the adapter.

## Transactional outbox

In each business transaction save state + history + outbox rows. A relay claims rows using a bounded lease/`FOR UPDATE SKIP LOCKED`, publishes to the broker and marks published **after** successful broker acknowledgement. Crash after publish but before marking causes duplicate publication; consumers must deduplicate. Crash before publication leaves the DB row recoverable. Do not mark published before a network call.

A consumer uses a stable effect key, such as `(consumer_name,event_id)` plus `(donation,round,step,input_version)` for workflow-level dedupe. Claim a receipt/lease, calculate external results outside the write transaction, then CAS-check input versions and commit effect + completed receipt + result outbox in one transaction. If a lease expires, recovery may retry. A unique receipt inserted before an effect but never completed must not cause that work to be skipped forever.

External side effects cannot generally be exactly once with a DB transaction. Notifications have a deterministic notification ID, outbox record and provider idempotency key when supported. For providers without idempotency, record attempts and possible duplicate delivery explicitly; do not claim guaranteed exactly-once SMS/email.

## Retry policy

Design defaults: provider timeout 10 seconds, at most 3 provider attempts, exponential backoff starting at 1 second with jitter capped at 30 seconds. Persist the total budget across worker redeliveries and cap by the donation’s last safe action time. Do not stack independent library retries that multiply the total silently. Schema/permission/expired-state errors are not retryable. A stale result is ignored, not retried against an obsolete version.

Current Celery defaults: JSON only, late acknowledgement, reject on worker loss, prefetch 1, soft/hard task limits 45/60 seconds, Redis visibility 300 seconds, no persisted Celery result backend. These settings allow duplicate delivery and do **not** implement durable receipts or a retry budget. Add the idempotent business transaction before enabling business tasks. Each long-running calculation must fit its task/provider deadline or be split into resumable steps.

Redis’s visibility timeout is not a business offer-expiry scheduler. Keep offers, reservations and step deadlines in PostgreSQL. A single elected scheduler/lease sweeps due rows and enqueues stable commands; multiple scheduler processes must not generate duplicate transitions. Celery heartbeat/inspect detects process health; the durable step lease detects abandoned work. Both are needed.

## Failure scenarios and required outcomes

| Injection | Correct result |
| --- | --- |
| API commits while Redis is down | Durable submission + unpublished outbox, or admission rejected before commit; no lost committed listing |
| Relay dies after publish | Duplicate event, one business effect |
| Worker dies after calculation | Expired step lease recovers; stale/duplicate result cannot overwrite current state |
| Recipient accepts while expiry job runs | One CAS transaction wins; other command conflicts or becomes a no-op |
| Driver declines after assignment | Release assignment and redispatch; keep recipient reservation while feasible |
| Route provider times out | Bounded retry/configured real fallback, or safely decline matching; no fabricated ETA |
| Model invents an ineligible ID | Reject output, record failure/fallback; never offer it |
| Deadline passes during provider call | Recheck clock at commit; no new offer/reservation/pickup |
| Persistent poison input | Durable failure/dead-letter record with reason and operator replay path |

Manual replay is authenticated, audited and checks current status/version/deadline before enqueueing. Replay does not reopen terminal donations or reset the total retry budget silently. Changes that require donor correction go back through explicit confirmation, not a modified hidden retry.

## Status distribution

Business events feed a durable audience-scoped stream after commit. A relay may use Redis pub/sub to wake API instances, but clients can always replay from database state. A PostgreSQL advisory-lock-elected publisher serializes stream cursor allocation over committed outbox events, independently of the broker relay; see [api.md](api.md) for ordering, retention and reconnect rules. Queue depth and retry metrics are operational observations, never the source of truth for a donation’s status.
