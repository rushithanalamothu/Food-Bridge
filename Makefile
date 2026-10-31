.PHONY: setup api web infra up down migrate contracts check integration worker

setup:
	uv sync --locked
	npm ci

api:
	uv run uvicorn foodbridge.api.main:app --reload --host 127.0.0.1 --port 8000

web:
	npm run dev

infra:
	docker compose up -d db redis

up:
	docker compose up --build -d

down:
	docker compose down

migrate:
	uv run alembic -c backend/alembic.ini upgrade head

contracts:
	uv run python scripts/export_contracts.py
	npm run contracts:types

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest -m "not integration"
	npm run format:check
	npm run typecheck
	npm test
	npm run build
	uv run python scripts/export_contracts.py --check
	npm run contracts:types -- --check
	uv run python scripts/check_docs.py
	docker compose config --quiet

integration:
	FOODBRIDGE_RUN_INTEGRATION=1 uv run pytest -m integration

# Example: make worker QUEUE=intake
worker:
	uv run celery -A foodbridge.agents.celery_app:celery_app worker -Q $(QUEUE) --loglevel=INFO --concurrency=1
