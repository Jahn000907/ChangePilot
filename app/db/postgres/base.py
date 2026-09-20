"""ChangePilot PostgreSQL base module.

Provides the shared SQLAlchemy 2.x declarative base for the PostgreSQL ORM
models of the ``erp`` / ``ecm`` / ``agent`` / ``audit`` schemas.

Scope: structure only.

- no business ORM model yet (models arrive in a later task);
- no table creation and no schema change: Alembic migrations own those
  (design doc v0.4 section 81);
- no database connection: this module is not involved in connection handling.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every PostgreSQL ORM model."""
