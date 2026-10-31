"""Bounded infrastructure probes. No credentials or raw exception strings are returned."""

import asyncio
from typing import Literal

import psycopg
from redis import Redis
from redis.exceptions import RedisError

from foodbridge.settings import Settings

DependencyStatus = Literal["ok", "unavailable"]


def _database(settings: Settings) -> DependencyStatus:
    try:
        url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url, connect_timeout=2, options="-c statement_timeout=2000") as conn:
            conn.execute("SELECT PostGIS_Version()").fetchone()
        return "ok"
    except (psycopg.Error, ValueError):
        return "unavailable"


def _redis(settings: Settings) -> DependencyStatus:
    try:
        with Redis.from_url(
            settings.redis_url, socket_connect_timeout=2, socket_timeout=2
        ) as client:
            client.ping()
        return "ok"
    except (RedisError, OSError, ValueError):
        return "unavailable"


async def check_dependencies(settings: Settings) -> dict[str, DependencyStatus]:
    database, redis = await asyncio.gather(
        asyncio.to_thread(_database, settings), asyncio.to_thread(_redis, settings)
    )
    return {"database": database, "redis": redis}
