# Contributing to FoodBridge

Read [setup](docs/setup.md), [design](docs/design.md) and [ownership](docs/team/ownership.md) before implementation. Work follows technical areas from Workbook 2, not old chapter assignments.

## Branch and review workflow

```sh
git switch main
git pull --ff-only
git switch -c feat/your-small-feature
```

Keep one cohesive feature per branch. Open a draft PR early for shared contracts/migrations; describe producer/consumer changes before teammates build against them. Rebase or merge current `main` before requesting review. Commit only your intended files; never use a force push on shared `main`. If you must update your own feature branch after rebase, use `--force-with-lease` and coordinate with anyone sharing it.

A PR contains implementation, meaningful tests, generated contract changes, migrations and documentation together. Run `make check`. Run `make integration` after database/queue changes, and the relevant acceptance cases after pipeline changes. Do not say a check passed if it was skipped or never run. Explain incomplete functionality and follow-up owner.

## Integration rules

- One canonical wire schema in `domain/contracts.py`; never maintain handwritten copies of shared wire types/statuses in the frontend.
- Change contracts additively, run `make contracts`, commit Python + JSON Schema + generated TypeScript + affected examples together. OpenAPI is generated from mounted routes only.
- Shared status/contract changes need producer and consumer review. Shared database changes need Rushitha’s coordination and the affected transaction owner’s review.
- One Alembic history. Add migrations for model changes, test on real PostgreSQL/PostGIS, do not edit merged revisions. No auto-create tables at startup.
- HTTP routes enforce membership; workers enforce state/version/deadline; provider adapters enforce timeouts. Keep those responsibilities in their own layers.
- No direct agent-to-agent business calls, arbitrary browser status updates, fake success endpoints or hidden unbounded retries.
- Add dependencies only for concrete needs; change lockfiles intentionally. Use `uv add` / `npm install --workspace ...` and commit the updated lockfiles.
- Do not commit `.env`, tokens, provider keys, real partner/location data, `node_modules`, `.venv`, generated runtime data or experiment outputs.

## Naming and layout

Python modules/functions: `snake_case`; class names: `PascalCase`; TypeScript components: `PascalCase`. Wire fields remain `snake_case`. Prefer small, named modules to general utility buckets. Role-specific UI stays under its feature; share a component only when two consumers actually need it.

New APIs declare request/response models and versioned error codes; new worker results include input versions and matching round. Include units in numeric fields. Use timezone-aware timestamps and inject clocks in rule/evaluation tests.

## Review standard

Reviewers check business invariants and cross-module behavior, not only formatting. For reservations inspect transaction boundaries, capacity and donation races, uniqueness, rollback, idempotency and deadline checks. For model/routing code inspect hard eligibility, timeout and unsafe-output behavior. For UI inspect actual server confirmation, conflict/reconnect states, keyboard access and responsive layout.

Repository admins should enable required CI and at least one review before merges. `CODEOWNERS` requests reviewers but does not enforce branch rules on its own. Until rules are configured, the same review discipline applies manually.
