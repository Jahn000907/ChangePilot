"""PostgreSQL-backed LangGraph checkpoints, separate from ECM business tables."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import InterfaceError, OperationalError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout
from sqlalchemy import text

from app.db.postgres.session import build_database_url, get_engine

SUPPLIER_EOL_NAMESPACE = "supplier_eol"
MATERIAL_SUBSTITUTION_NAMESPACE = "material_substitution"

_lock = Lock()
_shared: PostgresSaver | None = None
_pool: ConnectionPool | None = None


class CheckpointerUnavailableError(RuntimeError):
    """The durable checkpoint store cannot be reached or initialized."""


CHECKPOINT_CONNECTION_ERRORS = (
    CheckpointerUnavailableError, OperationalError, InterfaceError, PoolClosed, PoolTimeout,
)


def create_postgres_checkpointer() -> tuple[PostgresSaver, ConnectionPool]:
    """Open a process-owned pool and initialize official LangGraph tables.

    The caller owns the returned pool. ``setup`` is idempotent and is deliberately
    outside Alembic: these tables belong to LangGraph, not to the ECM schema.
    """
    url = build_database_url().set(drivername="postgresql")
    pool = ConnectionPool(
        conninfo=url.render_as_string(hide_password=False),
        kwargs={"autocommit": True, "row_factory": dict_row, "connect_timeout": 5},
        min_size=1,
        max_size=5,
        open=False,
    )
    try:
        pool.open(wait=True)
        saver = PostgresSaver(pool, serde=JsonPlusSerializer(
            allowed_msgpack_modules=[
                ("app.domain.dto.change_case", "SupplierEOLChangeCaseInput"),
                ("app.domain.dto.material_substitution", "MaterialSubstitutionInput"),
                ("app.domain.dto.material_substitution", "MaterialSubstitutionImpact"),
                ("app.domain.dto.strategy", "StrategyCandidate"),
                ("app.domain.dto.strategy", "StrategyType"),
                ("app.domain.dto.review", "ReviewResult"),
                ("app.domain.dto.review", "ReviewDecision"),
                ("app.domain.dto.approval", "HumanApproval"),
            ],
        ))
        saver.setup()
        return saver, pool
    except Exception as exc:
        pool.close()
        raise CheckpointerUnavailableError("PostgreSQL Checkpointer 连接或初始化失败") from exc


def get_postgres_checkpointer() -> PostgresSaver:
    """Lazily reuse one thread-safe saver across HTTP requests in this process."""
    global _shared, _pool
    with _lock:
        if _shared is None:
            _shared, _pool = create_postgres_checkpointer()
        return _shared


@contextmanager
def workflow_thread_lock(namespace: str, thread_id: str) -> Iterator[None]:
    """Serialize one thread's start/resume across FastAPI workers."""
    with get_engine().begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:namespace), hashtext(:thread_id))"),
            {"namespace": namespace, "thread_id": thread_id},
        )
        yield
