"""
Engine and session management.

The engine is created lazily. Building it at import time would mean the whole
FastAPI app fails to start when the database is unreachable, including the health
endpoint that is supposed to report that fact.
"""
import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base

# Matches the service in docker-compose.yml. Deliberately not defaulted to
# SQLite: a silent fallback to a local file would let the app look healthy while
# writing bot state and audit rows somewhere nobody is looking.
DEFAULT_DATABASE_URL = (
    'postgresql+psycopg://postgres:postgres@localhost:5432/trading_platform'
)

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def database_url() -> str:
    return os.getenv('DATABASE_URL', DEFAULT_DATABASE_URL)


def get_engine(url: Optional[str] = None, **kwargs) -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine, _session_factory

    if url is not None:
        # An explicit URL means a caller wants its own engine (tests, scripts).
        # Do not cache it as the process default.
        return _make_engine(url, **kwargs)

    if _engine is None:
        _engine = _make_engine(database_url(), **kwargs)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _make_engine(url: str, **kwargs) -> Engine:
    options = {
        # Verify a pooled connection before handing it out. Without this, a
        # connection dropped by a Postgres restart surfaces as a failed order
        # rather than as a reconnect.
        'pool_pre_ping': True,
        **kwargs,
    }
    if url.startswith('sqlite'):
        # SQLite has no pool sizing to speak of, and rejects the Postgres options.
        options.pop('pool_size', None)
        options.pop('max_overflow', None)

    engine = create_engine(url, **options)

    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def _enforce_sqlite_foreign_keys(dbapi_connection, _record):
            # SQLite ignores foreign keys unless asked not to. Without this the
            # test suite would pass while cascades and FK constraints did
            # nothing, which is worse than not testing them.
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

    return engine


def get_session_factory() -> sessionmaker:
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


@contextmanager
def session_scope(factory: Optional[sessionmaker] = None) -> Iterator[Session]:
    """A transactional session. Commits on success, rolls back on any exception.

    Rolling back rather than leaving a half-applied write is the point: a partly
    recorded order is a reconciliation failure waiting to happen.
    """
    factory = factory or get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine: Engine) -> None:
    """Create the schema directly from the models.

    For tests and throwaway databases only. Real databases are migrated with
    Alembic, so that a schema change is a reviewable file rather than whatever
    the models happened to say when the process last started.
    """
    Base.metadata.create_all(engine)


def reset_engine() -> None:
    """Drop the cached engine. Used by tests that swap databases."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
