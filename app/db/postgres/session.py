"""ChangePilot PostgreSQL session module.

Builds the SQLAlchemy 2.x engine and session factory for the PostgreSQL
database described by ``app.core.config``, using Psycopg 3 as the driver.

Scope:

- connection and session lifecycle only;
- no transaction helper: commit and rollback are owned by the business layer;
- no table creation and no migration: Alembic owns schema changes
  (design doc v0.4 section 81);
- importing this module never opens a connection. The engine is created
  lazily on the first call and cached afterwards.

Typical use::

    from sqlalchemy import text

    from app.db.postgres.session import create_session, get_engine

    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))

    with create_session() as session:
        session.execute(text("SELECT 1"))
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_database_url() -> URL:
    """Return the SQLAlchemy URL for the Psycopg 3 driver.

    ``URL.create`` is used instead of string concatenation so that a password
    containing ``@``, ``/``, ``:`` or spaces stays correct, and the resulting
    URL hides the password in its ``repr()``.
    """
    postgres = get_settings().postgres
    return URL.create(
        drivername="postgresql+psycopg",
        username=postgres.user,
        password=postgres.password.get_secret_value(),
        host=postgres.host,
        port=postgres.port,
        database=postgres.db,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide engine.

    The engine is created lazily: importing this module does not touch the
    database, the first connection happens on first use.

    ``pool_pre_ping`` discards connections that the database or a Docker
    restart already dropped. ``hide_parameters`` keeps statement parameters out
    of error messages and logs (design doc v0.4 section 86 / 88), and
    ``application_name`` makes this application visible in ``pg_stat_activity``
    while ``connect_timeout`` keeps an unreachable database from hanging.
    """
    return create_engine(
        build_database_url(),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"application_name": "changepilot", "connect_timeout": 5},
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory bound to the shared engine."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def create_session() -> Session:
    """Create a new session bound to the shared engine.

    The caller owns the transaction boundary: commit or rollback explicitly, or
    use the session as a context manager (which closes it without committing).
    """
    return get_session_factory()()
