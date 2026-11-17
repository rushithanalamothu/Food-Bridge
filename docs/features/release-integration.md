# Tej's release integration

This extends the merged AI orchestrator and reservation/pickup workflow. It implements browser authentication, SMTP delivery, operator snapshots/history, driver delivery detail, connected driver/operations screens, and self-hosted deployment/verification tooling. It does not implement Rushitha's production matching/routing or Mithil's recipient/profile workspace.

## Browser authentication

The gateway implements OIDC authorization code + PKCE with state and nonce validation. Access/refresh tokens remain server-side in Redis under opaque-session hashes. The browser receives an HttpOnly, SameSite=Lax cookie (Secure outside local development). There are no browser-stored access tokens. Configure the existing issuer, audience and JWKS plus `FOODBRIDGE_BROWSER_AUTH_ENABLED`, `FOODBRIDGE_OIDC_CLIENT_ID` and `FOODBRIDGE_PUBLIC_URL`. A confidential provider can also use `FOODBRIDGE_OIDC_CLIENT_SECRET`.

The callback validates the signed ID token, nonce, audience/issuer and consistency with the verified access-token subject. Login state is single-use and bound to a browser cookie. Refresh is serialized with a Redis lock, rotates refresh tokens when supplied, and cannot resurrect a concurrently logged-out session. Sessions have an absolute lifetime. The callback permits only the known workspace return paths. State-changing cookie requests require a trusted Origin; bearer clients retain existing behavior. Invalid cookies never become demo identities.

`GET /api/v1/auth/session` lists only active server-managed memberships. The header selector narrows them; it cannot grant a role. The same selection now applies to donor organizations. Logout deletes the server session, clears browser cookies and attempts refresh-token revocation when the provider advertises it. This is application logout; an identity provider may retain its separate SSO session.

Provision memberships with the trusted server CLI, never with browser claims:

```sh
uv run python scripts/provision_member.py --subject VERIFIED_OIDC_SUBJECT --organization-id EXISTING_ORG_UUID --role donor --display-name 'Demo donor'
```

Creating a user in Keycloak does not automatically grant FoodBridge access. The subject must be provisioned against an existing organization. Login/provider tokens must not be printed in logs; the release stack disables API access logging so authorization codes are not logged from callback query strings. Redis contains credential material and must remain private, backed by protected storage. Losing Redis sessions requires users to sign in again; reservation truth remains in PostgreSQL.

## External notification adapter

`notification_mode=smtp` selects a real SMTP adapter through the existing durable notification worker. It resolves the notification's user to a consent-attested contact and checks current user/activity/audience membership before sending. An optional domain allowlist constrains test destinations. TLS uses the system trust store; unauthenticated plaintext transport is permitted only in local development. SMTP calls are bounded and occur outside database write transactions.

Contacts use the additive migration `74f61c890a12`, following `6331d74ea8b4`. No preexisting user is opted in automatically. A trusted administrator must first verify address ownership and consent, then provision it:

```sh
uv run python scripts/provision_member.py --subject VERIFIED_OIDC_SUBJECT --organization-id EXISTING_ORG_UUID --role donor --display-name 'Demo donor' --email VERIFIED_TEST_ADDRESS --attest-verified-contact-and-consent
```

Email contains an event name and sign-in link, not donor text, locations or model output. Stable Message-ID values correlate retries. A sent receipt means SMTP acceptance, not guaranteed inbox delivery/read status. SMTP has no universal idempotency guarantee: an ambiguous acceptance can cause duplicate mail on retry. Invalid/missing/disabled contacts fail without exposing their address or provider exception in routine logs. A provider's verified sender and credentials are still required to deliver over the public internet. No public SMS adapter is claimed.

## Driver and operations handoff

The driver screen calls existing assignment/accept/decline/pickup/delivery commands. Pickup requires explicit handling/quantity confirmation; delivery requires separate confirmation. The server enforces versions, actor scope, quantity and expiry rules. The driver response adds receiving organization, delivery location and a timestamped route snapshot. It never represents that saved estimate as live navigation.

Operator routes now include:

- `GET /api/v1/operations/donations` with bounded cursor pagination.
- `GET /api/v1/operations/donations/{id}` for a current scoped snapshot.
- `GET /api/v1/operations/donations/{id}/history?after_version=0&limit=100` with version pagination.

The operations screen consumes those reads plus summary, failure/replay and orchestrator-audit APIs. Events trigger fresh snapshots; reconnect and expired cursors reconcile snapshots. The connection state is visible. Actor changes restart requests; server authorization remains authoritative. Driver/operations integration is shared with Mithil; visual polish and the recipient workspace remain his team's frontend work.

The additive DTOs come from canonical Python models and regenerated schema/TypeScript/OpenAPI. A stale command refreshes current state; request identities are retained across an unchanged client retry. The operator release check is aligned with the donor-organization scope used by operations reads and failures.

## Isolated local acceptance stack

The overrides use their own Compose project, volumes, ports and session-cookie name; they do not overwrite `.env` or the ordinary demo database. Start Docker and run from the repository root:

```sh
FOODBRIDGE_BACKEND_IMAGE=foodbridge-backend:release-local docker compose -p foodbridge-release -f compose.yaml -f compose.release-local.yml up --build -d
FOODBRIDGE_BACKEND_IMAGE=foodbridge-backend:release-local docker compose -p foodbridge-release -f compose.yaml -f compose.release-local.yml exec -T api uv run --no-sync python scripts/seed_release_demo.py
```

Open <http://localhost:55173>. Sign in as `tej-demo` with password `foodbridge-local-only`. These are explicitly synthetic local-only credentials, never imported by the production configuration generator. The local Keycloak administration page is <http://localhost:58080>; its bootstrap user is `local-admin` with the same local-only password. The test inbox is <http://localhost:58025>. Every permitted SMTP destination ends in `example.test`, so no public recipient receives a message.

The local OIDC test identity has donor/recipient/driver/operator memberships. The seed binds the synthetic driver to that identity in this isolated database. These demo memberships are not a production provisioning policy. Existing fixture receiving/driver windows are preserved and expire; use a separate fresh project or reviewed versioned fixture updates when needed, never drop shared data to make a test pass.

Run the release browser acceptance against that running stack:

```sh
FOODBRIDGE_RELEASE_E2E=1 npm run test:e2e
```

The test uses real Keycloak login, API cookies, PostgreSQL/Redis/workers, driver/operations browser interactions and a Mailpit SMTP inbox. Recipient acceptance uses its real API because the recipient screen is another owner's pending work. Matching/routing remains explicitly synthetic. This local test defaults to rules-mode AI so it consumes no Gemini quota; model behavior is covered separately by the orchestrator suite.

## Self-hosted deployment and operations

See [deployment](../deployment.md). `deploy/compose.production.yml` is a separate public-host profile: production-built static frontend, Caddy TLS and immediate SSE forwarding, PostgreSQL/PostGIS, private Redis, all four workers/relays, self-hosted Keycloak with its own database, and protected Prometheus metrics. Only the web gateway publishes ports. The local test realm/passwords and Mailpit are absent from production.

Generate private runtime configuration after choosing two DNS names and reviewed unique image tags/digests:

```sh
uv run python scripts/init_deployment.py --domain food.example.org --auth-domain login.example.org --backend-image registry.example.org/foodbridge-api:REVIEWED_SHA --web-image registry.example.org/foodbridge-web:REVIEWED_SHA
```

This writes ignored `deploy/runtime/runtime.env`, `realm.json` and a monitoring credential. It refuses to overwrite existing credentials. Domains must point to the host and ports 80/443 must be reachable before public certificate issuance works. Build the web image with `deploy/Dockerfile.web`; the same backend image must be used by API and workers. Configure real matching, model/provider secrets and SMTP separately. Generated settings keep notification sending disabled until explicitly configured.

The Keycloak bootstrap administrator is `foodbridge-admin`; its generated password is in the private runtime file. Create real provider users there and provision their verified subjects/memberships using the CLI. After bootstrap, replace the bootstrap credential and restrict identity administration according to your host policy.

`GET /internal/metrics` requires a private bearer token and is blocked at the public gateway. Metrics cover outbox backlog, due steps, queue sizes and notification states. Prometheus includes unavailable/stalled/failure rules. Alert delivery to an external on-call destination still requires a chosen receiver; this setup does not send unsolicited alerts.

Backup and isolated restore verification:

```sh
uv run python scripts/database_backup.py --compose deploy/compose.production.yml --env-file deploy/runtime/runtime.env backup --archive deploy/backups/BEFORE_RELEASE.dump
uv run python scripts/database_backup.py --compose deploy/compose.production.yml --env-file deploy/runtime/runtime.env verify-restore --archive deploy/backups/BEFORE_RELEASE.dump
```

Quiesce writers for a comparable verification snapshot. Dumps have mode 0600; encrypt and copy them to protected off-host storage under your retention policy. Restore creates only a new `foodbridge_restore_*` database, never overwrites live data, compares migration/counts and checks active-reservation uniqueness. A failed isolated target remains for inspection; remove it deliberately when finished. Provider notification reconciliation remains an operator decision when recovering real production state.

Promote or roll back image references:

```sh
uv run python scripts/release_control.py --record deploy/releases/NEW_RELEASE.json --backend-image registry.example.org/foodbridge-api:NEW_SHA --web-image registry.example.org/foodbridge-web:NEW_SHA
uv run python scripts/release_control.py --record deploy/releases/ROLLBACK.json --rollback deploy/releases/NEW_RELEASE.json
```

The tool records previous image references, applies additive migrations on promotion, starts the consistent service set and checks readiness/migration state. Rollback never automatically downgrades a database. Confirm schema compatibility before rolling images back. The tool also runs `scripts/smoke_gateway.py` against the public HTTPS origin to verify static serving, API readiness and internal-route isolation. A ready service set is still recorded as awaiting authenticated acceptance, not as a verified end-to-end release.

A real server/domain, sender/provider account, production matching/routing and final browser acceptance are still prerequisites for shared release sign-off. Local tests and deployable files cannot establish that an unprovisioned public environment is working.
