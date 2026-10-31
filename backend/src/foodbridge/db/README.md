# Database workspace — Rushitha

One SQLAlchemy Base and Alembic history serve all agents. The initial migration enables PostGIS; the intake migration adds identity, drafts, donations, history, idempotency, outbox and evaluation tables. Extend the existing `models.py` rather than creating a second schema. Recipient/capacity, matching/reservation and generic recovery storage remain next work, defined in the repository data-model document.

Import every new mapped entity into Alembic's metadata loading before running autogenerate. Coordinate migration heads and transaction constraints with the affected owner. Never create business tables during app startup. Run `alembic check`, infrastructure integration tests and relevant real-DB races.
