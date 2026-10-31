"""Run against real infrastructure with make integration; no SQLite substitution."""

import asyncio
import os

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from foodbridge.db.health import check_dependencies
from foodbridge.settings import Settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FOODBRIDGE_RUN_INTEGRATION") != "1",
        reason="Run make integration with services up",
    ),
]


def test_database_postgis_redis_and_migration_head():
    settings = Settings()
    assert asyncio.run(check_dependencies(settings)) == {"database": "ok", "redis": "ok"}
    expected = ScriptDirectory.from_config(Config("backend/alembic.ini")).get_current_head()
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == expected
            )
    finally:
        engine.dispose()
