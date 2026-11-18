# FoodBridge web applications — Mithil

One React/TypeScript application serves donor, receiver (`/recipient`), driver and operations workspaces. Read the root README, `docs/design.md`, `docs/team/ownership.md`, and `CONTRIBUTING.md` before changing shared behavior.

## Run

Use Node 22 and `npm ci` from the repository root. Follow `docs/setup.md` for Python 3.12, API, PostgreSQL/PostGIS, Redis, migrations and workers. Run `npm run dev`; Vite proxies `/api` to the API on port 8000. `npm run build` creates a static build. Existing Docker web service remains development-only.

For the explicitly synthetic local workflow enable the backend's local intake/workflow flags and sandbox notifications, apply migrations, run both seed scripts and start all four queues plus workflow runtime. See `docs/features/workflow.md`. The frontend never grants demo identity; the server must opt in locally.

## Implemented applications

- **Donor:** persisted extraction/review/confirmation, explicit-allergen validation, pickup-location timezone input (ambiguous/skipped DST times rejected), saved-draft ID recovery, donation detail/status, paginated recent donations, cancellation and session activity.
- **Receiver:** paginated offers, route/explanation/expiry, explicit accept/decline, versioned reservation commands and persisted reservation lookup/release after reload, full food details/history and versioned receiving-profile/capacity editing.
- **Driver:** paginated assignments, food/storage/allergen/handling details, accept/decline, observed-weight/handling confirmation, pickup and delivery commands, verified receiving destination and map link.
- **Operations:** organization summaries, explicitly labeled synthetic impact, status counts, paginated failures, decision audits, guarded replay and session activity. Replay uses a version observed in the decision audit; the server rejects stale or impermissible attempts.
- **Shared:** responsive navigation/cards/forms, keyboard focus/labels, honest loading/empty/error states, verified session identity, scoped API wrappers, command idempotency and authenticated fetch SSE.

SSE subscribes before a reconciliation snapshot, reuses its in-memory cursor on reconnect, drops repeated cursor IDs, resets expired cursors and refreshes authoritative snapshots. Streams stop on authorization failure. Workspace changes close streams, clear role-local data and reconnect under the selected membership. Older list pages reset after a fresh live snapshot so stale actions are not retained. Activity lists contain only events received during the mounted session; they are not a complete historical timeline.

Donation detail refreshes are tied to the current donor selection. Starting another donation invalidates outstanding detail requests. History clears the previous resource immediately when selecting a different donation, including when the new request fails. Operations replay is available only after both the selected donation snapshot and its audit load successfully; a failed or pending review cannot reuse a previous donation's version.

## Organization sign-in

Copy this directory's `.env.example` to `.env.local`. Configure a public OIDC Authorization Code + PKCE client through `VITE_OIDC_AUTHORITY`, `VITE_OIDC_CLIENT_ID`, `VITE_OIDC_SCOPE` and optional `VITE_OIDC_AUDIENCE`. Register the exact `<web-origin>/auth/callback` redirect URI and allow this origin at the provider's discovery/token endpoints. Use HTTPS for shared deployments. Do not set a client secret in the SPA. Coordinate issuer, audience, JWKS, memberships and provider provisioning with Tej.

The `oidc-client-ts` integration retains access/ID tokens in memory. Only temporary authorization-request state/PKCE data uses sessionStorage; donor recovery also stores a draft UUID, never draft text. Tokens are never placed in stream URLs or localStorage. A reload requires signing in again; automatic refresh/silent renewal is intentionally disabled until provider behavior is configured. Sign out removes the FoodBridge session; it does not sign out of the external identity provider. Existing gateway integrations may also supply tokens using the shared in-memory setter. Organization selection uses server-returned memberships and never grants access, including donors with multiple memberships.

## Backend integration and review

Role applications now use additive `/receiving-profile`, `/reservations`, `/workflow/donations` and `/memberships` read/command APIs. Offers include food details; pickup snapshots include receiver destination/name. Newest-first reads are explicit `order=newest` queries, preserving the existing oldest-first default for other consumers. Donation history is durable server history, separate from session-only event activity. Operator replay uses a freshly authorized donation version rather than guessing from a planning audit.

Receiver saves require the current profile version and every capacity version, with a stable idempotency key. The transaction locks existing profile/capacity rows, preserves committed inbound weight, rejects capacity below commitments or unsupported precision, increments versions and saves an audience-scoped outbox event with the receipt. Location changes remain coordinator-verified because routing must use verified coordinates. Users can edit categories, storage, free capacity, rejected allergens, required diet and receiving windows. New receiving locations and account provisioning remain onboarding work.

Existing offers shown before a successful receiving-preference save or an observed profile-version change are marked as needing revalidation and cannot be accepted. A `recipient_profile_changed` acceptance conflict produces the same guidance after refreshing the authoritative snapshot. Decline remains available. Replacement match IDs remain actionable; the UI never reports that rematching has been queued.

**Backend follow-up (Tej with Rushitha/Mokshith):** profile updates currently invalidate the profile version captured in existing match candidates, but do not automatically schedule donation revalidation/rematching. The offer read model does not expose that candidate profile version, so a newly loaded browser cannot identify every stale offer before its first acceptance conflict. The UI safeguards apply to profile changes observed during the mounted workspace and explicit conflicts; they do not implement backend rematching. Coordinate that workflow/contract change separately, preserving deterministic eligibility and transactional reservation checks.

Membership menus list only memberships returned for the verified subject. Donor identity now honors a selected authorized organization. Cross-organization reads return 404; unauthorized roles return 403. Read models share existing tables; no migration or lifecycle change was introduced. Canonical `domain/workflow.py` changes generate JSON Schema/OpenAPI/TypeScript through `make contracts`.

The original frontend integration was merged in PR #9. Affected-owner review covers Tej for API/auth/SSE and shared dependency wiring; Rushitha for capacity/profile locking and data projections; Mokshith for eligibility/profile inputs. No approval is inferred from a review request. Live matching, routing-provider availability, external notifications, live identity-provider provisioning and production hosting remain team/deployment responsibilities.

## Verification

From the root: `make check`. Run `make integration` and the existing worker smokes against real PostgreSQL/PostGIS and Redis for integrated acceptance.

`npm test` covers API error behavior, command headers/retries, explicit allergens, timezone/DST conversion and SSE framing/deduplication/reconnect/auth boundaries. Install Chromium with `npm exec --workspace @foodbridge/web -- playwright install chromium`.

- `npm run test:e2e --workspace @foodbridge/web -- workspaces.spec.ts` exercises contract-shaped mocked HTTP receiver/driver/operations interactions, conflicts and mobile layout. These are browser integration tests with synthetic fixtures, not proof of database transactions or live model behavior.
- `npm run test:e2e --workspace @foodbridge/web -- state-recovery.spec.ts` covers delayed donor refresh success/failure after starting a new donation, cross-donation history loading/failure, replay review/version isolation, preference-save invalidation, acceptance conflicts and replacement offers. Requests are explicitly gated to reproduce races deterministically.
- `npm run test:e2e --workspace @foodbridge/web -- intake.spec.ts` requires the real local intake stack. The CI integration job runs both browser specs and real worker smoke scripts.

Tests and builds use committed generated types. Never hand-edit `src/api/generated/`.

Browser coverage also exercises receiver preference editing, reservation recovery after reload, newest-first pagination, SSE replay/cursor-expiry/auth failure, keyboard skip navigation and WCAG A/AA axe checks across all four workspaces. `auth.spec.ts` uses a separate test-only Vite server on 5174 and an intercepted standards-shaped OIDC provider to exercise real `oidc-client-ts` Code+PKCE processing, callback-state rejection, bearer requests and memory-only token/logout behavior. These protocol fixtures do not claim verification of an externally provisioned vendor account. The ordinary dev server does not inherit the fixture configuration.

For real end-to-end browser acceptance, after seeding workflow identities and starting every queue and the workflow runtime: `FOODBRIDGE_RUN_FULL_BROWSER=1 npm run test:e2e --workspace @foodbridge/web -- full-workflow.spec.ts`. This submits through the donor UI, accepts through the receiver UI, confirms pickup/delivery as the driver, and checks donor history and the operations board using actual HTTP/DB/queues. It is separately gated so the intake-only stage can run without racing general orchestration.
