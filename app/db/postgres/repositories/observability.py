"""Read-only queries for existing trace, audit and execution records."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.postgres.models.agent import AgentRun, AgentStep, ToolCall
from app.db.postgres.models.audit import AuditEvent
from app.db.postgres.models.ecm import (
    ChangeCase,
    EngineeringChangeOrder,
    EngineeringChangeRequest,
    ExecutionJob,
)


class ObservabilityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def recent_runs(self, limit: int) -> list[AgentRun]:
        return list(self._session.scalars(
            select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
        ))

    def run(self, run_id: uuid.UUID) -> AgentRun | None:
        return self._session.get(AgentRun, run_id)

    def steps(self, run_id: uuid.UUID) -> list[AgentStep]:
        return list(self._session.scalars(
            select(AgentStep).where(AgentStep.run_id == run_id)
            .order_by(AgentStep.started_at, AgentStep.step_id)
        ))

    def tool_calls(self, run_id: uuid.UUID) -> list[ToolCall]:
        return list(self._session.scalars(
            select(ToolCall).where(ToolCall.run_id == run_id)
            .order_by(ToolCall.created_at, ToolCall.tool_call_id)
        ))

    def audits(self, run_id: uuid.UUID) -> list[AuditEvent]:
        return list(self._session.scalars(
            select(AuditEvent).where(AuditEvent.run_id == run_id)
            .order_by(AuditEvent.created_at, AuditEvent.audit_id)
        ))

    def thread_id(self, case_id: uuid.UUID) -> str | None:
        case = self._session.get(ChangeCase, case_id)
        if case is None:
            return None
        key = case.idempotency_key or ""
        for prefix in ("api:supplier-eol:", "material-substitution:"):
            if key.startswith(prefix):
                return key[len(prefix):]
        return None

    def execution_jobs(self, case_id: uuid.UUID) -> list[ExecutionJob]:
        return list(self._session.scalars(
            select(ExecutionJob).join(
                EngineeringChangeOrder,
                ExecutionJob.eco_id == EngineeringChangeOrder.eco_id,
            ).join(
                EngineeringChangeRequest,
                EngineeringChangeOrder.ecr_id == EngineeringChangeRequest.ecr_id,
            ).where(EngineeringChangeRequest.case_id == case_id)
            .order_by(ExecutionJob.created_at, ExecutionJob.execution_job_id)
        ))
