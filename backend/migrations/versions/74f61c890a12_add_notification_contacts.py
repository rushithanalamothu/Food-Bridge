"""Add consent-attested notification destinations; no existing rows are enabled.

Revision ID: 74f61c890a12
Revises: 6331d74ea8b4
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "74f61c890a12"
down_revision = "6331d74ea8b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_contacts",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_notification_contacts_version_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notification_contacts_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_contacts")),
    )


def downgrade():
    op.drop_table("notification_contacts")
