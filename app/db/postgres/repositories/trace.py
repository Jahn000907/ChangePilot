"""Minimal persistence operations for agent trace and audit records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.postgres.models.agent import AgentRun, AgentStep, ToolCall
from app.db.postgres.models.audit import AuditEvent


class TraceRepository:
    """Write-only repository for the current workflow observability scope."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_agent_run(
        self,
        *,
        run_id: uuid.UUID,
        case_id: uuid.UUID,
        workflow_name: str,
        workflow_version: str,
        model_provider: str | None,
        model_name: str | None,
        started_at: datetime,
    ) -> None:
        self._session.add(
            AgentRun(
                run_id=run_id,
                case_id=case_id,
                workflow_name=workflow_name,
                workflow_version=workflow_version,
                status="RUNNING",
                model_provider=model_provider,
                model_name=model_name,
                started_at=started_at,
                finished_at=None,
                input_tokens=0,
                output_tokens=0,
                total_cost=None,
                latency_ms=None,
                error_message=None,
            )
        )
        self._session.flush()

    def update_agent_run_case_id(self, run_id: uuid.UUID, case_id: uuid.UUID) -> None:
        result = self._session.execute(
            update(AgentRun).where(AgentRun.run_id == run_id).values(case_id=case_id)
        )
        if result.rowcount != 1:
            raise LookupError(f"Agent Run {run_id} does not exist")

    def update_agent_run_status(
        self,
        *,
        run_id: uuid.UUID,
        status: str,
        finished_at: datetime | None,
        latency_ms: int | None,
        error_message: str | None,
    ) -> None:
        result = self._session.execute(
            update(AgentRun)
            .where(AgentRun.run_id == run_id)
            .values(
                status=status,
                finished_at=finished_at,
                latency_ms=latency_ms,
                error_message=error_message,
            )
        )
        if result.rowcount != 1:
            raise LookupError(f"Agent Run {run_id} does not exist")

    def create_agent_step(
        self,
        *,
        step_id: uuid.UUID,
        run_id: uuid.UUID,
        node_name: str,
        agent_name: str | None,
        input_summary: dict[str, Any],
        started_at: datetime,
    ) -> None:
        self._session.add(
            AgentStep(
                step_id=step_id,
                run_id=run_id,
                node_name=node_name,
                agent_name=agent_name,
                status="RUNNING",
                input_summary=input_summary,
                output_summary=None,
                started_at=started_at,
                finished_at=None,
                latency_ms=None,
                error_message=None,
            )
        )
        self._session.flush()

    def complete_agent_step(
        self,
        *,
        step_id: uuid.UUID,
        status: str,
        output_summary: dict[str, Any] | None,
        finished_at: datetime,
        latency_ms: int,
        error_message: str | None,
    ) -> None:
        result = self._session.execute(
            update(AgentStep)
            .where(AgentStep.step_id == step_id)
            .values(
                status=status,
                output_summary=output_summary,
                finished_at=finished_at,
                latency_ms=latency_ms,
                error_message=error_message,
            )
        )
        if result.rowcount != 1:
            raise LookupError(f"Agent Step {step_id} does not exist")

    def create_tool_call(
        self,
        *,
        tool_call_id: uuid.UUID,
        run_id: uuid.UUID,
        step_id: uuid.UUID | None,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        self._session.add(
            ToolCall(
                tool_call_id=tool_call_id,
                run_id=run_id,
                step_id=step_id,
                agent_name=agent_name,
                tool_name=tool_name,
                tool_mode="READ",
                arguments=arguments,
                result_summary=None,
                status="STARTED",
                latency_ms=None,
            )
        )
        self._session.flush()

    def complete_tool_call(
        self,
        *,
        tool_call_id: uuid.UUID,
        status: str,
        result_summary: dict[str, Any],
        latency_ms: int,
    ) -> None:
        result = self._session.execute(
            update(ToolCall)
            .where(ToolCall.tool_call_id == tool_call_id)
            .values(
                status=status,
                result_summary=result_summary,
                latency_ms=latency_ms,
            )
        )
        if result.rowcount != 1:
            raise LookupError(f"Tool Call {tool_call_id} does not exist")

    def create_audit_event(
        self,
        *,
        audit_id: uuid.UUID,
        case_id: uuid.UUID | None,
        run_id: uuid.UUID,
        actor_type: str,
        actor_id: str,
        action: str,
        object_type: str,
        object_id: str,
        after_state: dict[str, Any] | None,
        event_metadata: dict[str, Any] | None,
    ) -> None:
        self._session.add(
            AuditEvent(
                audit_id=audit_id,
                case_id=case_id,
                run_id=run_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                object_type=object_type,
                object_id=object_id,
                before_state=None,
                after_state=after_state,
                event_metadata=event_metadata,
            )
        )
        self._session.flush()
