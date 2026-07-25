"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the process-wide SQLAlchemy engine.

    Raises:
        ConfigurationError: when no database URL is configured.
    """
    settings: Settings = get_settings()
    if not settings.database_url:
        msg = "SENTINEL_DATABASE_URL is not configured"
        raise ConfigurationError(msg, details={"setting": "SENTINEL_DATABASE_URL"})
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": settings.db_connect_timeout_s},
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope around a series of operations."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> bool:
    """Return ``True`` when the database answers a trivial query.

    Never raises: readiness reporting must not turn into a 500.
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure at all means "not ready"
        return False
    return True


def reset_engine_cache() -> None:
    """Drop cached engine and session factory. Used by tests and by reconfiguration."""
    get_engine.cache_clear()
    get_session_factory.cache_clear()
