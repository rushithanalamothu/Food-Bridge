"""Engines are local to an API/worker process; no connections at module import."""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker


@lru_cache(maxsize=8)
def engine_for(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def session_factory(url: str):
    return sessionmaker(engine_for(url), expire_on_commit=False)
