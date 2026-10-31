# Database workspace — Rushitha

One SQLAlchemy Base and Alembic history serve all agents. The initial migration enables PostGIS only. Business entities, repositories and transaction helpers are next work, defined in `docs/architecture/data-model.md`.

Import every new mapped entity into Alembic's metadata loading before running autogenerate. Coordinate migration heads and transaction constraints with the affected owner. Never create business tables during app startup. Run `alembic check`, infrastructure integration tests and relevant real-DB races.
