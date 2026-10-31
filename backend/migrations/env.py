"""One migration history for the shared database; do not create per-agent histories."""

from alembic import context
from sqlalchemy import create_engine, pool, text

from foodbridge.db import models  # noqa: F401 -- register all application metadata
from foodbridge.db.base import Base
from foodbridge.settings import Settings


def include_object(obj, name, type_, reflected, compare_to):
    # PostGIS owns these reflected tables; they are not application migration targets.
    return name not in {"spatial_ref_sys", "geometry_columns", "geography_columns"}


if context.is_offline_mode():
    context.configure(
        url=Settings().database_url, target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(Settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        # The official image adds Tiger schemas to search_path. Autogeneration must
        # inspect application tables in public, not extension-owned geocoder tables.
        connection.execute(text("SET search_path TO public"))
        connection.commit()
        context.configure(
            connection=connection, target_metadata=Base.metadata, include_object=include_object
        )
        with context.begin_transaction():
            context.run_migrations()
