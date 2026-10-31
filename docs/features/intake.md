# Intake and Eligibility — Mokshith

Implemented feature boundary: describe food → persisted extraction draft → donor correction/confirmation → committed donation, history and handoff event → typed eligibility evaluation on a worker. Matching, recipient reservation, driver assignment and live status streaming remain their owners’ work.

## Run the local flow

Use the normal setup/migrations first. Set `FOODBRIDGE_ENABLE_LOCAL_INTAKE_DEMO=true` in your private root `.env`; it defaults to false and is rejected outside `environment=local`. This is a synthetic local donor identity, not production authentication. Never enable it on a shared/public host.

Native hot-reload workflow:

```sh
make migrate
make seed-intake-demo
make api
```

In separate terminals run `make web`, `make worker QUEUE=intake`, and `make intake-relay`. Open <http://localhost:5173/donor>. The screen uses the real API/database. Try:

```text
Food: vegetable rice bowls. 20 meals, 10 kg. Refrigerated. Vegetarian.
Allergens: soy. Tomorrow pickup 10 AM to 12 PM. Use by 2 PM.
```

Correct every proposed field and explicitly confirm the review checkbox. The dates in the form use the browser timezone, shown beside the controls. Missing information stays blank; required food/quantity/storage/allergen/time fields must be supplied before posting.

For Compose, set the same private `.env` flag, run `make up`, then provision the demo identity:

```sh
docker compose exec -T api uv run --no-sync python scripts/seed_intake_demo.py
uv run python scripts/smoke_intake.py
```

The bounded smoke command creates synthetic local records and exercises HTTP → PostgreSQL → Redis → actual intake worker. The demo-recipient button uses **synthetic** route/driver facts and one capacity-compatible recipient plus one smaller recipient. It does not select a match or reserve food. Results remain in `intake_evaluations`; replaying worker delivery cannot duplicate the result event.

## Contracts and endpoints

Canonical types: `backend/src/foodbridge/domain/intake.py`. Exports: `contracts/intake.schema.json` and `apps/web/src/api/generated/intake.ts`; regenerate with `make contracts`.

- `GET /api/v1/me`: verified, active donor membership and pickup site. One donor membership is supported in this slice; multiple memberships return a selection-required conflict for the gateway owner to extend.
- `POST /donation-drafts`: `DraftCreate`, idempotency UUID header → 201 completed `DraftRead`. Extraction is synchronous with a bounded provider call, so it returns a ready-to-review draft rather than an unfinished 202 job.
- `GET /donation-drafts/{id}`: owner-scoped draft and current version/confirmation state.
- `POST /donations`: `DonationSubmit` wraps draft ID, expected version, `confirmed=true` and corrected `DonationInput` → 202 `IntakeDonationRead`. It commits submission but does not claim matching succeeded.
- `GET /donations` and `/donations/{id}`: owner-scoped snapshots and computed urgency; cursor/limit pagination on the list.
- `POST /donations/{id}/demo-eligibility`: local-demo-only, no client candidate facts; 202 persisted evaluation job, with its own idempotency key.
- `GET /intake/evaluations/{id}`: owner-scoped pending/completed/stale/failed result.

All mutation commands require `Idempotency-Key`. Changed input under an existing key conflicts. A second command key cannot post a confirmed draft again. Stale drafts return 409. Past deadlines, unsupported quantity precision and unknown/conflicting allergen declarations return 422 without changing the draft or writing a partial donation. Queue envelopes contain IDs/version metadata, not addresses or food descriptions.

## Extraction modes

With no configured key (or explicit `FOODBRIDGE_AI_PROVIDER=rules`), basic extraction is deliberately conservative and labelled “Basic extraction · no model used.” Explicit food labels, weights, portions, storage, allergen declarations and unambiguous today/tomorrow AM/PM windows can be proposed. Missing/ambiguous facts require review. This is a deterministic baseline, not an LLM or a trained spoilage predictor.

The app-wide AI client supports OpenAI (the API used for GPT models), Google Gemini and Anthropic Claude, plus configurable OpenAI-compatible Chat Completions endpoints. Keys are read by the backend only; never put them in `VITE_*` variables or commit `.env`. Consumer ChatGPT/Claude subscriptions are not API credentials.


**One AI configuration for the whole app.** All model-backed features must call `integrations.ai.generate_structured` with the shared `Settings`; they supply only feature instructions, input and a Pydantic output type. This client handles provider HTTP, schema normalization, timeouts and local output validation. Intake uses it now. Future matching/ranking must reuse it; those model-backed business features are not implemented yet. Do not add feature-specific provider/key/model settings or provider HTTP clients. `FOODBRIDGE_AI_PROVIDER`, `FOODBRIDGE_AI_API_KEY`, `FOODBRIDGE_AI_MODEL`, `FOODBRIDGE_AI_BASE_URL`, `FOODBRIDGE_AI_RESPONSE_FORMAT` and `FOODBRIDGE_AI_TIMEOUT_S` apply to every caller in API and worker processes. Eligibility and urgency remain pure deterministic rules and need no model key.

The previous `FOODBRIDGE_EXTRACTION_*` environment names remain deprecated aliases for these same global settings. Global names take precedence when both are present; a legacy extraction key cannot select a separate intake provider. Compose applies the same precedence. Prefer the global names in new `.env` files.

Set `FOODBRIDGE_AI_PROVIDER=auto` (the new default) and **one** of these in the root `.env`:

| Key | Selected provider | Default model (override for your account) |
| --- | --- | --- |
| `OPENAI_API_KEY` | `openai` | `gpt-4.1-mini` |
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | `gemini` | `gemini-2.5-flash` |
| `ANTHROPIC_API_KEY` | `anthropic` | `claude-sonnet-4-5` |

`FOODBRIDGE_OPENAI_API_KEY`, `FOODBRIDGE_GEMINI_API_KEY` and `FOODBRIDGE_ANTHROPIC_API_KEY` are also accepted. Standard key names take precedence over their prefixed aliases; `GEMINI_API_KEY` takes precedence over `GOOGLE_API_KEY`. No key means basic rules extraction. Multiple vendor keys require an explicit `FOODBRIDGE_AI_PROVIDER`; ambiguous configuration fails at startup without printing keys. Explicit `rules` disables all remote calls even when keys are present. Existing `.env` files with `provider=rules` must change to `auto` to enable key detection.

For explicit selection, set the provider and either its vendor key or `FOODBRIDGE_AI_API_KEY` (the latter takes precedence). Override the default model with `FOODBRIDGE_AI_MODEL`; available models and structured-output support depend on your account. The legacy explicit OpenAI + generic key/model configuration remains supported. Restart native API/worker processes, or run `docker compose up --build -d`, after changing settings. Compose passes the same settings to all backend processes, never to the web build.

For another service, select `openai_compatible`, set `FOODBRIDGE_AI_API_KEY`, `FOODBRIDGE_AI_MODEL` and `FOODBRIDGE_AI_BASE_URL` (an HTTPS API base such as `https://your-provider.example/v1`). The adapter appends `/chat/completions` and uses bearer authentication. It requires JSON Schema structured outputs by default; set `FOODBRIDGE_AI_RESPONSE_FORMAT=json_object` for endpoints that support JSON mode only. This supports that protocol, not every provider's proprietary API, Azure deployment routing, Bedrock or Vertex credentials. The base URL is trusted deployment configuration: it receives the selected generic key and donor description. Native provider URLs cannot be overridden.

All adapters use a bounded timeout (`FOODBRIDGE_AI_TIMEOUT_S`, default 8 seconds, maximum 20), JSON/schema validation and source-quote checks. OpenAI sets `store=false`. Claude receives a schema with unsupported numeric/string constraints removed; full local Pydantic validation still enforces them. Refusal, truncation, blocked, malformed or failed responses fall back visibly to basic extraction. There is no automatic cross-vendor fallback or credential probing. The UI records the provider/model that actually produced the proposal. Donor confirmation and deterministic safety rules remain mandatory. No live provider key was used for automated tests; protocol, failure and environment-selection tests use HTTP mock transports.

Provider references: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/generate-content/structured-output), [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

## Eligibility and urgency

`policy.evaluate(donation, batch, now, policy)` is a pure entry point usable by both Rushitha’s matching strategies. Input includes donation/recipient versions, route timestamp/source and driver window/capacity/storage. Every failing gate produces a stable reason code. Unknown/unverified recipients, stale/estimated routes, missing drivers, wrong food/storage/diet, insufficient storage-specific capacity, incompatible allergens and infeasible pickup/arrival deadlines fail closed.

Allergen vocabulary is explicit and versioned in `policy.py`; aliases normalize terms such as soya/soy, peanuts/peanut and dairy/milk. Unrecognized or uncertain allergen text requires correction; it is never equivalent to “none.” Contradictory declared dietary/allergen claims also require correction. Rules compare declared information; they do not certify food safety or dietary compliance.

Pickup feasibility accounts for travel to donor, donor pickup window, 15-minute handling buffer, route duration, recipient receiving window, driver availability and safe-use deadline. It can delay pickup to meet a recipient’s opening time. Urgency uses the **donor-confirmed deadline**, with configurable critical/high windows; it never extends that deadline or claims a predictive spoilage probability.

`config/intake.json` is the authoritative eligibility/urgency configuration; validate bounds/order and bump its version when behavior changes. Services load it once per process; restart services after editing. `config/matching.json` owns ranking settings only.

## Persistence and team handoff

Migration `36120ccc9d0d` adds minimal users/organizations/memberships, drafts, donations, history, idempotency, outbox and evaluation storage. Organizations use PostGIS geography; confirmed donation details are a validated JSON snapshot with queryable quantity/deadline/status/version columns. Tej/Rushitha should extend these models/history, not create a competing schema. A review of these shared tables and additive contracts is needed before merging.

Submission holds the draft row lock, rechecks owner/status/version, writes donation + history + `donation.submitted.v1` + saved idempotent response in one transaction. Distinct concurrent commands on a draft yield one committed donation. Its submission event remains unpublished for the orchestrator’s future relay/consumer; the intake relay intentionally claims only `intake.evaluation_requested.v1` events.

Trusted backend producers can call `IntakeService.request_evaluation(actor, batch, key, correlation_id)` with real current candidate facts. The worker takes only a persisted evaluation ID, checks the donation version/state and commits result + `intake.evaluated.v1` atomically. `allow_synthetic` is false by default. The local demo explicitly enables it. Results carry recipient versions for later revalidation at reservation; no capacity is consumed by evaluation.

The relay leases unpublished intake requests before broker publication, marks them published only after publish returns, and retries unpublished leases after 30 seconds. A crash between publish and marking can redeliver; the evaluation row lock makes the committed effect idempotent. Celery retries transient DB failures three times. General workflow recovery/dead-letter operations and dispatch of donation-submitted events remain Tej’s integration work; this feature does not claim a complete recovery scheduler.

## Shared authentication boundary

Outside the demo, the dependency verifies RS256 JWT signature, issuer, audience, required subject/issued-at/expiry using configured HTTPS JWKS with caching/timeouts. It then resolves a server-managed active donor membership. Token/body role or organization claims do not grant data access. The gateway owner must configure the OIDC provider, provision users/memberships and connect browser login. `setIntakeAccessToken()` accepts an in-memory gateway token; nothing is stored in localStorage or query strings. A malformed token never falls back to demo identity.

## Verification

`make check` covers pure policy/extraction, mocked model responses, JWT negatives, schema/type drift and frontend API behavior. `make integration` creates a temporary, uniquely named PostgreSQL database for the intake suite (the local/CI role needs CREATE DATABASE permission), applies migrations, and removes that test database afterward. This isolates tests from a running demo relay/worker. It covers real PostgreSQL transactions, concurrent posts, ownership, replay, stale evaluation inputs and broker-publication recovery. `scripts/smoke_intake.py` covers the running broker/worker path. With that stack running, install the browser once using `npm exec --workspace @foodbridge/web -- playwright install chromium`, then run `npm run test:e2e` for the desktop/mobile donor review and worker flow. CI runs both smoke paths. These checks establish this feature, not the entire workbook’s matching/reservation acceptance suite.
