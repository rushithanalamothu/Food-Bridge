"""Enable PostGIS; business tables belong to the next coordinated migration.

Revision ID: 0001
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    # Extension ownership can predate this application; never drop it automatically.
    pass
