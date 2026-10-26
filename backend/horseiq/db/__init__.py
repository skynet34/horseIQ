from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event

from ..config import get_settings
from .schema import metadata


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite ignores FKs unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def init_db(engine: Engine) -> None:
    metadata.create_all(engine)


@lru_cache
def get_engine() -> Engine:
    engine = make_engine(get_settings().database_url)
    init_db(engine)
    return engine
