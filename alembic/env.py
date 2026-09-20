"""ChangePilot Alembic environment.

The database URL is never hardcoded: it is built by
``app.db.postgres.session.build_database_url()`` from the application
settings, which read the project root ``.env`` file. Neither ``alembic.ini``
nor this module contains a user, password, host, port or database name.

``alembic.ini`` puts the project root on ``sys.path`` through
``prepend_sys_path``, so ``app`` imports work no matter which working
directory alembic is started from.

Schema handling follows design doc v0.4 section 24: the four business schemas
``erp`` / ``ecm`` / ``agent`` / ``audit`` are covered by ``include_schemas``,
while the ``alembic_version`` table stays in the default schema.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import create_engine

# The project root must be importable before "app" is imported below. This is
# done explicitly rather than relying on prepend_sys_path alone, because Alembic
# splits that option on ":" unless path_separator is configured, which would
# break an absolute Windows path such as D:\ChangePilot.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic import context
from app.db.postgres import models  # noqa: F401  (registers models on Base.metadata)
from app.db.postgres.base import Base
from app.db.postgres.session import build_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The ORM models are added to this metadata in a later task; autogenerate
# compares against it.
target_metadata = Base.metadata

# Compare and create objects across every business schema (v0.4 section 24).
INCLUDE_SCHEMAS = True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode, emitting SQL to stdout."""
    context.configure(
        # The URL is rendered only here, in memory, for offline SQL generation.
        url=build_database_url().render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=INCLUDE_SCHEMAS,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live connection.

    ``NullPool`` is used because a migration run is a short-lived process: no
    connection should be kept around afterwards.
    """
    connectable = create_engine(build_database_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=INCLUDE_SCHEMAS,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
