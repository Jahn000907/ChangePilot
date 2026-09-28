"""Business-friendly, redacted read view over Agent Trace and Audit."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.postgres.repositories.observability import ObservabilityRepository
from app.db.postgres.session import create_session
from app.domain.dto.observability import (
    AgentRunDetail,
    AgentRunSummary,
    AgentStepView,
    AuditEventView,
    ExecutionJobView,
    ToolCallView,
)

_SAFE_ARGUMENTS = frozenset({
    "part_number", "revision_code", "as_of_date", "product_part_number",
    "order_number", "supplier", "supplier_code", "search", "open_only",
    "max_depth", "candidate_part_number", "warehouse_code", "plant_code",
})


class ObservabilityService:
    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._sessions = session_factory or create_session

    def recent_runs(self, limit: int = 30) -> list[AgentRunSummary]:
        with self._sessions() as session:
            repo = ObservabilityRepository(session)
            return [self._summary(row, repo) for row in repo.recent_runs(limit)]

    def run_detail(self, run_id: uuid.UUID) -> AgentRunDetail:
        with self._sessions() as session:
            repo = ObservabilityRepository(session)
            run = repo.run(run_id)
            if run is None:
                raise LookupError("运行记录不存在")
            steps = repo.steps(run_id)
            calls = repo.tool_calls(run_id)
            by_step: dict[uuid.UUID, list[ToolCallView]] = {}
            for row in calls:
                if row.step_id is not None:
                    by_step.setdefault(row.step_id, []).append(self._call(row))
            step_views = [AgentStepView(
                step_id=row.step_id, node_name=row.node_name, agent_name=row.agent_name,
                status=row.status, started_at=row.started_at, finished_at=row.finished_at,
                duration_ms=self._duration(row.started_at, row.finished_at, row.latency_ms),
                summary=self._step_summary(row.node_name, row.output_summary, row.status),
                tool_calls=by_step.get(row.step_id, []),
            ) for row in steps]
            audits = [AuditEventView(
                audit_id=row.audit_id, action=row.action, actor_type=row.actor_type,
                object_type=row.object_type, object_id=row.object_id,
                created_at=row.created_at,
            ) for row in repo.audits(run_id)]
            jobs = [ExecutionJobView(
                execution_job_id=row.execution_job_id, eco_id=row.eco_id,
                action_type=row.action_type,
                title=str(row.payload.get("title") or row.action_type)[:120],
                description=str(row.payload.get("description") or "受控执行任务")[:300],
                owner_department=str(row.payload.get("owner_department"))[:80]
                if row.payload.get("owner_department") else None,
                status=row.status,
                related_part_number=str(row.payload.get("part_number"))[:64]
                if row.payload.get("part_number") else None,
                created_at=row.created_at,
            ) for row in repo.execution_jobs(run.case_id)]
            return AgentRunDetail(
                **self._summary(run, repo, steps=steps, calls=calls).model_dump(),
                steps=step_views, audit_events=audits, execution_jobs=jobs,
            )

    @classmethod
    def _summary(
        cls, run: object, repo: ObservabilityRepository,
        *, steps: list[object] | None = None, calls: list[object] | None = None,
    ) -> AgentRunSummary:
        steps = steps if steps is not None else repo.steps(run.run_id)
        calls = calls if calls is not None else repo.tool_calls(run.run_id)
        planned = next((step for step in steps if step.node_name == "supervisor_plan"), None)
        selected = (planned.output_summary or {}).get("agents", []) if planned else []
        if not isinstance(selected, list):
            selected = []
        return AgentRunSummary(
            run_id=run.run_id, thread_id=repo.thread_id(run.case_id),
            workflow_name=run.workflow_name, status=run.status,
            started_at=run.started_at, finished_at=run.finished_at,
            duration_ms=cls._duration(run.started_at, run.finished_at, run.latency_ms),
            error_summary="运行失败，详情请查看后端日志。" if run.status == "FAILED" else None,
            has_supervisor=planned is not None,
            selected_agents=[str(name) for name in selected],
            called_tools=list(dict.fromkeys(call.tool_name for call in calls)),
        )

    @staticmethod
    def _duration(started: datetime, finished: datetime | None, stored: int | None) -> int | None:
        if stored is not None:
            return max(0, stored)
        end = finished or datetime.now(UTC)
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return max(0, int((end - started).total_seconds() * 1000))

    @staticmethod
    def _step_summary(node: str, output: dict[str, object] | None, status: str) -> str:
        if status == "FAILED":
            return "执行失败；内部错误详情已隐藏。"
        if status == "WAITING_HUMAN":
            return "等待人工审批。"
        data = output or {}
        if node == "supervisor_plan":
            names = data.get("agents")
            return "选择领域：" + "、".join(map(str, names)) if isinstance(names, list) and names else "无需多智能体分析。"
        if node == "supervisor_summary":
            return "领域结果已汇总。"
        if node.endswith("Agent"):
            return f"核验事实 {data.get('fact_count', 0)} 项，待确认 {data.get('unknown_count', 0)} 项。"
        if node == "execution":
            return f"已创建 {data.get('execution_job_count', 0)} 个受控执行任务。"
        return "步骤已完成。"

    @staticmethod
    def _call(row: object) -> ToolCallView:
        arguments = {
            key: value for key, value in (row.arguments or {}).items()
            if key in _SAFE_ARGUMENTS and isinstance(value, (str, int, float, bool, type(None)))
        }
        preview = (row.result_summary or {}).get("content_preview", "")
        summary = "查询失败。" if row.status == "FAILED" else "查询已完成。"
        if row.status == "SUCCEEDED":
            try:
                data = json.loads(str(preview))
                if isinstance(data, list):
                    summary = f"返回 {len(data)} 条记录。"
                elif isinstance(data, dict):
                    for key in ("rows", "products", "totals"):
                        if isinstance(data.get(key), (list, dict)):
                            summary = f"返回 {len(data[key])} 项{key}结果。"
                            break
            except (ValueError, TypeError):
                pass
        return ToolCallView(
            tool_call_id=row.tool_call_id, step_id=row.step_id,
            tool_name=row.tool_name, agent_name=row.agent_name, status=row.status,
            duration_ms=row.latency_ms, created_at=row.created_at,
            arguments=arguments, result_summary=summary,
        )
