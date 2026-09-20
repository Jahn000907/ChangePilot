"""Shared plumbing for the read-only PostgreSQL repositories.

The repositories in this package own the SQLAlchemy statements and convert
database rows into plain frozen dataclasses ("facts"). They never return an ORM
instance or a ``Row`` to a caller, and they contain no business rules: deciding
what a fact means belongs to the service layer.

A repository can either use the shared session factory or an injected session,
which is what the unit tests use.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.db.postgres.session import create_session


class ReadOnlyRepository:
    """Base class that manages the session lifecycle of a read-only repository."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def _fetch_all(self, statement: Select[Any]) -> Sequence[Any]:
        """Execute a SELECT and return its rows.

        When a session was injected it stays open (the caller owns it); otherwise
        a short-lived session is created and closed here.
        """
        if self._session is not None:
            return list(self._session.execute(statement))
        with create_session() as session:
            return list(session.execute(statement))
