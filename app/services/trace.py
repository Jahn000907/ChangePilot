"""Small service boundary for workflow trace and audit writes."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.db.postgres.repositories.trace import TraceRepository
from app.db.postgres.session import create_session

logger = logging.getLogger(__name__)


class TraceService:
    """Create required Run/Step records and best-effort detail records."""

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory = session_factory or create_session
        self._current_step_id: ContextVar[uuid.UUID | None] = ContextVar(
            f"trace_step_{id(self)}", default=None
        )
        self._run_started: dict[uuid.UUID, datetime] = {}

    @property
    def current_step_id(self) -> uuid.UUID | None:
        return self._current_step_id.get()

    def create_run(self, run_id: uuid.UUID, *, workflow_name: str = "supplier_eol") -> None:
        """Create the required base Run with a temporary correlation case UUID."""
        started_at = datetime.now(UTC)
        self._write(
            lambda repository: repository.create_agent_run(
                run_id=run_id,
                case_id=run_id,
                workflow_name=workflow_name,
                workflow_version="1.0",
                model_provider="deepseek",
                model_name=None,
                started_at=started_at,
            )
        )
        self._run_started[run_id] = started_at

    def attach_case(self, run_id: uuid.UUID, case_id: uuid.UUID) -> None:
        """Replace the temporary Run correlation UUID with the persisted case ID."""
        self._write(
            lambda repository: repository.update_agent_run_case_id(run_id, case_id)
        )

    def update_run_status(
        self,
        run_id: uuid.UUID,
        status: str,
        *,
        error: str | None = None,
        required: bool = False,
    ) -> None:
        finished = datetime.now(UTC) if status in {"SUCCEEDED", "FAILED", "CANCELLED"} else None
        started = self._run_started.get(run_id)
        latency_ms = (
            int((datetime.now(UTC) - started).total_seconds() * 1000)
            if started is not None and finished is not None
            else None
        )
        operation = lambda repository: repository.update_agent_run_status(
            run_id=run_id,
            status=status,
            finished_at=finished,
            latency_ms=latency_ms,
            error_message=error,
        )
        if required:
            self._write(operation)
        else:
            self._best_effort(operation, "update Agent Run status")

    def start_step(
        self,
        *,
        run_id: uuid.UUID,
        node_name: str,
        agent_name: str | None,
        input_summary: dict[str, Any],
    ) -> tuple[uuid.UUID, float]:
        step_id = uuid.uuid4()
        self._write(
            lambda repository: repository.create_agent_step(
                step_id=step_id,
                run_id=run_id,
                node_name=node_name,
                agent_name=agent_name,
                input_summary=input_summary,
                started_at=datetime.now(UTC),
            )
        )
        return step_id, perf_counter()

    def finish_step(
        self,
        *,
        step_id: uuid.UUID,
        started_clock: float,
        status: str,
        output_summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        latency_ms = int((perf_counter() - started_clock) * 1000)
        self._best_effort(
            lambda repository: repository.complete_agent_step(
                step_id=step_id,
                status=status,
                output_summary=output_summary,
                finished_at=datetime.now(UTC),
                latency_ms=latency_ms,
                error_message=error,
            ),
            "complete Agent Step",
        )

    @contextmanager
    def bind_step(self, step_id: uuid.UUID) -> Iterator[None]:
        token = self._current_step_id.set(step_id)
        try:
            yield
        finally:
            self._current_step_id.reset(token)

    def start_tool_call(
        self,
        *,
        run_id: uuid.UUID,
        tool_name: str,
        arguments: dict[str, Any],
        agent_name: str = "ReviewAgent",
    ) -> tuple[uuid.UUID, float] | None:
        tool_call_id = uuid.uuid4()
        try:
            self._write(
                lambda repository: repository.create_tool_call(
                    tool_call_id=tool_call_id,
                    run_id=run_id,
                    step_id=self.current_step_id,
                    agent_name=agent_name,
                    tool_name=tool_name,
                    arguments=arguments,
                )
            )
        except Exception:
            logger.exception("Unable to create Tool Call trace")
            return None
        return tool_call_id, perf_counter()

    def finish_tool_call(
        self,
        handle: tuple[uuid.UUID, float] | None,
        *,
        status: str,
        result_summary: dict[str, Any],
    ) -> None:
        if handle is None:
            return
        tool_call_id, started_clock = handle
        self._best_effort(
            lambda repository: repository.complete_tool_call(
                tool_call_id=tool_call_id,
                status=status,
                result_summary=result_summary,
                latency_ms=int((perf_counter() - started_clock) * 1000),
            ),
            "complete Tool Call",
        )

    def audit(
        self,
        *,
        run_id: uuid.UUID,
        case_id: uuid.UUID | None,
        actor_type: str,
        actor_id: str,
        action: str,
        object_type: str,
        object_id: str,
        after_state: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._best_effort(
            lambda repository: repository.create_audit_event(
                audit_id=uuid.uuid4(),
                case_id=case_id,
                run_id=run_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                object_type=object_type,
                object_id=object_id,
                after_state=after_state,
                event_metadata=metadata,
            ),
            "create Audit Event",
        )

    def _write(self, operation: Callable[[TraceRepository], None]) -> None:
        session = self._session_factory()
        try:
            operation(TraceRepository(session))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _best_effort(
        self,
        operation: Callable[[TraceRepository], None],
        description: str,
    ) -> None:
        try:
            self._write(operation)
        except Exception:
            logger.exception("Trace write failed: %s", description)
