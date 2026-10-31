# Deployment and operational plan

The Compose file is a local development profile. Cloud provider/host selection remains a team task. Do not expose its example database credentials, unauthenticated placeholder routes or Vite dev server publicly.

## Current foundation versus planned operations

Current: health/dependency probes, donor intake persistence/confirmation, JWT membership verification, intake evaluation worker/relay, local demo opt-in, request IDs, migrations, web review flow and CI. Planned: identity provider provisioning/browser login, general orchestrator relay/recovery/expiry scheduling, matching/reservation, authenticated SSE, broader metrics/error budgets and shared demo hosting. The implementation plan assigns those tasks.

## Promotion order

1. Pin reviewed backend/frontend build SHA and lockfiles. Deploy the same image to API and workers; frontend is a static build behind HTTPS/reverse proxy.
2. Inject runtime secrets through the host’s secret store, not Git or frontend bundles. Set explicit CORS/issuer/audience/JWKS and sandbox notification providers.
3. Back up DB and verify restore on a separate database before a schema change. Run one migration job; application replicas do not race to migrate themselves.
4. Start DB/Redis, migration, API, workers, outbox relay and elected scheduler. Use dependency readiness plus worker/queue/lease monitoring; process startup is not business readiness.
5. Run an authenticated synthetic donor → offer → reserve → pickup → delivery smoke test, one decline/re-match, one stale-version conflict, and one reconnect/replay.
6. Check scoped SSE authorization, reverse proxy buffering/idle timeouts, sandbox notification destination allowlist and no secrets/PII in logs. Mark demo metrics synthetic.

Redis is transport/cache, not the record of reservations. Enable suitable Redis persistence/retention but recover workflow from DB outbox/history. Database backups include outbox/receipts/stream cursor state; document retention and avoid replaying historical external notifications on restore without effect reconciliation.

## Health and observability

Liveness confirms API response. Readiness currently probes PostGIS + Redis only; it does not certify migration head or business-worker health. Deployment migration verification and worker probes are separate gates. Extend readiness deliberately if the service starts depending on additional critical components.

Required dashboards as the pipeline lands: per-agent queue depth/oldest age, workflow lease age, outbox lag, SSE lag, provider latency/error, stale-result count, reservation conflict/capacity rejection count, deadline expiries and persistent failures. Alert on lost or duplicated effects and constraint violations, not merely CPU. Log structured request/correlation/event IDs and sanitized reasons.

## Rollback

Roll back API/workers/frontend together to a compatible build SHA. Do not blindly reverse destructive migrations or drop a PostGIS volume. Prefer additive schema changes and forward fixes; restore a backup only through a documented recovery operation with state/effect reconciliation. Retain immutable status history and replay records. Re-run the smoke test and record actual operator, SHA, migration head and incident reason.
