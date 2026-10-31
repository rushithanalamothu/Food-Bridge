# Web workspace — Mithil

One React/TypeScript codebase serves `/donor`, `/recipient`, `/driver` and `/operations`. The donor route implements real draft review and submission; the other role routes remain implementation placeholders. See [the intake runbook](../../docs/features/intake.md). The HTML mockup in [the design reference](../../docs/design/ui/foodbridge.html) is simulated and is not copied into production behavior.

Run `npm run dev` from root; the Vite `/api` proxy targets `localhost:8000`. Docker sets its internal target to `api:8000`. Build/typecheck/test with root commands. Node 22 is the team baseline.

Put role pages/components/hooks in `src/features/<role>`, genuinely shared UI in `src/components`, HTTP/SSE/auth wrappers in `src/api`, styling in `src/styles`. Shared domain types come from `src/api/generated/domain.ts`; run `make contracts` at root to refresh. Do not duplicate status enums or make browser-selected roles authoritative.

First handoff: typed donor draft/review UI with missing-field, confirmation and error states. Build against fixtures while API contracts land. Acceptance requires mobile/keyboard usability, server-confirmed reservation state, stale-version refetch, authorized snapshots and stream reconnect behavior. Backend owners provide their example payloads before integration. See [ownership](../../docs/team/ownership.md) and [API/SSE contract](../../docs/architecture/api.md).
