"""SQLAlchemy engine configuration without leaking database credentials."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import Settings, get_settings


def get_database_url(settings: Settings | None = None) -> URL | str:
    """Build the PostgreSQL URL from either one URL or discrete environment values."""
    settings = settings or get_settings()
    if settings.qfae_database_url:
        url = settings.qfae_database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url
    return URL.create(
        drivername="postgresql+psycopg",
        username=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )


@lru_cache
def get_engine() -> Engine:
    """Return the process-wide, connection-pooled PostgreSQL engine."""
    return create_engine(
        get_database_url(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 3},
    )


def database_is_available(engine: Engine | None = None) -> bool:
    """Check connectivity without exposing connection details."""
    try:
        with (engine or get_engine()).connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1
    except Exception:
        return False

