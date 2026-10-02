"""Safe, compact read contracts for the Agent run center."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AgentRunSummary(BaseModel):
    run_id: uuid.UUID
    thread_id: str | None = None
    workflow_name: str
    status: str
    analysis_status: str | None = None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    error_summary: str | None = None
    has_supervisor: bool = False
    agent_count: int = 0
    selected_agents: list[str] = Field(default_factory=list)
    called_tools: list[str] = Field(default_factory=list)


class ToolCallView(BaseModel):
    tool_call_id: uuid.UUID
    step_id: uuid.UUID | None
    tool_name: str
    agent_name: str
    status: str
    duration_ms: int | None
    created_at: datetime
    arguments: dict[str, object]
    result_summary: str


class AgentStepView(BaseModel):
    step_id: uuid.UUID
    node_name: str
    agent_name: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    summary: str
    tool_calls: list[ToolCallView] = Field(default_factory=list)


class AuditEventView(BaseModel):
    audit_id: uuid.UUID
    action: str
    actor_type: str
    object_type: str
    object_id: str
    created_at: datetime


class ExecutionJobView(BaseModel):
    execution_job_id: uuid.UUID
    eco_id: uuid.UUID
    action_type: str
    title: str
    description: str
    owner_department: str | None
    status: str
    related_part_number: str | None
    created_at: datetime


class AgentRunDetail(AgentRunSummary):
    steps: list[AgentStepView]
    audit_events: list[AuditEventView]
    execution_jobs: list[ExecutionJobView]
