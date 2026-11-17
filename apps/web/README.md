# FoodBridge web applications — Mithil

One React/TypeScript application serves donor, receiver (`/recipient`), driver and operations workspaces. Read the root README, `docs/design.md`, `docs/team/ownership.md`, and `CONTRIBUTING.md` before changing shared behavior.

## Run

Use Node 22 and `npm ci` from the repository root. Follow `docs/setup.md` for Python 3.12, API, PostgreSQL/PostGIS, Redis, migrations and workers. Run `npm run dev`; Vite proxies `/api` to the API on port 8000. `npm run build` creates a static build. Existing Docker web service remains development-only.

For the explicitly synthetic local workflow enable the backend's local intake/workflow flags and sandbox notifications, apply migrations, run both seed scripts and start all four queues plus workflow runtime. See `docs/features/workflow.md`. The frontend never grants demo identity; the server must opt in locally.

## Implemented applications

- **Donor:** persisted extraction/review/confirmation, explicit-allergen validation, pickup-location timezone input (ambiguous/skipped DST times rejected), saved-draft ID recovery, donation detail/status, paginated recent donations, cancellation and session activity.
- **Receiver:** paginated offers, route/explanation/expiry, explicit accept/decline, versioned reservation commands and release of holds accepted during the current mounted workspace.
- **Driver:** paginated assignments, food/storage/allergen/handling details, accept/decline, observed-weight/handling confirmation, pickup and delivery commands.
- **Operations:** organization summaries, explicitly labeled synthetic impact, status counts, paginated failures, decision audits, guarded replay and session activity. Replay uses a version observed in the decision audit; the server rejects stale or impermissible attempts.
- **Shared:** responsive navigation/cards/forms, keyboard focus/labels, honest loading/empty/error states, verified session identity, scoped API wrappers, command idempotency and authenticated fetch SSE.

SSE subscribes before a reconciliation snapshot, reuses its in-memory cursor on reconnect, drops repeated cursor IDs, resets expired cursors and refreshes authoritative snapshots. Streams stop on authorization failure. Workspace changes close streams, clear role-local data and reconnect under the selected membership. Older list pages reset after a fresh live snapshot so stale actions are not retained. Activity lists contain only events received during the mounted session; they are not a complete historical timeline.

## Organization sign-in

Copy this directory's `.env.example` to `.env.local`. Configure a public OIDC Authorization Code + PKCE client through `VITE_OIDC_AUTHORITY`, `VITE_OIDC_CLIENT_ID`, `VITE_OIDC_SCOPE` and optional `VITE_OIDC_AUDIENCE`. Register the exact `<web-origin>/auth/callback` redirect URI and allow this origin at the provider's discovery/token endpoints. Use HTTPS for shared deployments. Do not set a client secret in the SPA. Coordinate issuer, audience, JWKS, memberships and provider provisioning with Tej.

The `oidc-client-ts` integration retains access/ID tokens in memory. Only temporary authorization-request state/PKCE data uses sessionStorage; donor recovery also stores a draft UUID, never draft text. Tokens are never placed in stream URLs or localStorage. A reload requires signing in again; automatic refresh/silent renewal is intentionally disabled until provider behavior is configured. Sign out removes the FoodBridge session; it does not sign out of the external identity provider. Existing gateway integrations may also supply tokens using the shared in-memory setter. Organization selection narrows existing server memberships and never grants access. Donor `/me` currently supports only one donor membership.

## Backend handoff and limitations

No wire contracts, lifecycle states, Python service, or migrations were changed. Required follow-up reviews: Tej for OIDC/session/API/SSE integration and the new browser dependency/lockfile; Rushitha for receiver/profile/offer data; Mokshith for donor review/time handling. The following are deliberately not simulated:

1. Receiver profile/capacity/preferences read/write APIs are absent; editing is unavailable.
2. Offers currently expose donation IDs, routing and explanation but omit food/quantity/allergen detail. Receiver food-detail screens need an authorized read model from the backend owners.
3. Reservation list/detail reads are absent. A newly accepted hold can be released during the mounted session; after a reload/navigation the accepted offer remains visible, but hold lookup/release requires coordinator assistance. Reservation receipt data is not persisted in browser storage.
4. Driver assignment reads omit receiver delivery destination/navigation. The UI instructs drivers to obtain it from the coordinator; no location is invented.
5. Operator reads provide aggregate status and planning audits, not a complete donation-detail/history board. Replay can only be offered when a donation version appears in an audit.
6. Live matching/routing and real notification providers remain backend dependencies. All test fixtures and demo impact are synthetic.

Agree additive read/command models in an issue or draft PR with the named owners before changing shared Python contracts; regenerate all artifacts using `make contracts`. Keep one migration history coordinated by Rushitha if storage changes become necessary.

## Verification

From the root: `make check`. Run `make integration` and the existing worker smokes against real PostgreSQL/PostGIS and Redis for integrated acceptance.

`npm test` covers API error behavior, command headers/retries, explicit allergens, timezone/DST conversion and SSE framing/deduplication/reconnect/auth boundaries. Install Chromium with `npm exec --workspace @foodbridge/web -- playwright install chromium`.

- `npm run test:e2e --workspace @foodbridge/web -- workspaces.spec.ts` exercises contract-shaped mocked HTTP receiver/driver/operations interactions, conflicts and mobile layout. These are browser integration tests with synthetic fixtures, not proof of database transactions or live model behavior.
- `npm run test:e2e --workspace @foodbridge/web -- intake.spec.ts` requires the real local intake stack. The CI integration job runs both browser specs and real worker smoke scripts.

Tests and builds use committed generated types. Never hand-edit `src/api/generated/`.
