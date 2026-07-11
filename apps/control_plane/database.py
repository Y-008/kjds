from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DEFAULT_DATABASE_URL = "postgresql+psycopg://hermes:hermes_dev@localhost:5432/hermes"


def database_url() -> str:
    return os.getenv("KJDS_DATABASE_URL", DEFAULT_DATABASE_URL)


def create_database_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True)


def database_health(engine: Engine | None = None) -> dict[str, str]:
    target = engine or create_database_engine()
    with target.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
