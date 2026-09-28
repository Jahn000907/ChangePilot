"""Integration tests for the Supplier EOL strategy-review workflow."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import date

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from neo4j.exceptions import Neo4jError
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.agents.review import ReviewAgent
from app.agents.strategy import StrategyAgent
from app.db.neo4j.driver import close_driver, get_driver
from app.db.postgres.models.agent import AgentRun, AgentStep, ToolCall
from app.db.postgres.models.audit import AuditEvent
from app.db.postgres.models.ecm import (
    ChangeCase,
    ChangeImpact,
    ChangeStrategy,
    ChangeStrategyAction,
    EngineeringChangeOrder,
    EngineeringChangeRequest,
    ExecutionJob,
)
from app.db.postgres.session import create_session
from app.domain.dto.approval import HumanApproval
from app.domain.dto.change_case import SupplierEOLChangeCaseInput
from app.domain.errors import EntityNotFoundError
from app.tools import get_review_tools
from app.workflows import (
    ReviewStatus,
    StrategyGenerationStatus,
    SupplierEOLWorkflowState,
    SupplierEOLWorkflowStatus,
    WorkflowRunStatus,
    build_supplier_eol_workflow,
    resume_supplier_eol_workflow,
    run_supplier_eol_workflow,
)


class _FakeStrategyLLM:
    """Return a deterministic strategy and record revision feedback usage."""

    def __init__(self) -> None:
        self.call_count = 0
        self.feedback_call_count = 0

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        assert "only the supplied facts" in system_prompt
        assert '"part_number":"BRG-6204-A"' in user_prompt
        if '"review_feedback":' in user_prompt:
            self.feedback_call_count += 1
        return json.dumps(
            {
                "strategies": [
                    {
                        "strategy_type": "LAST_TIME_BUY",
                        "title": "Evaluate a bounded last-time buy",
                        "summary": "Use confirmed demand and supply facts to size the option.",
                        "rationale": "The supplier notice includes a last-time-buy window.",
                        "actions": ["Validate demand horizon", "Confirm supplier capacity"],
                        "risks": ["Planned purchase quantities may not arrive on time"],
                    }
                ]
            }
        )


class _ToolThenPassReviewLLM:
    """Request one real read-only Tool, then return a PASS review."""

    def __init__(self) -> None:
        self.call_count = 0
        self.received_tool_message = False

    def invoke_with_tools(
        self,
        *,
        messages: Sequence[BaseMessage],
        tools: Sequence[BaseTool],
    ) -> AIMessage:
        self.call_count += 1
        assert {tool.name for tool in tools} == {
            "find_where_used",
            "get_inventory",
            "get_purchase_orders",
            "get_alternatives",
            "get_bom_structure",
        }
        if self.call_count == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_alternatives",
                        "args": {
                            "part_number": "BRG-6204-A",
                            "revision_code": "A",
                        },
                        "id": "review-tool-call-1",
                        "type": "tool_call",
                    }
                ],
            )

        tool_message = messages[-1]
        assert isinstance(tool_message, ToolMessage)
        self.received_tool_message = True
        tool_payload = json.loads(str(tool_message.content))
        assert tool_payload["part_number"] == "BRG-6204-A"
        return AIMessage(
            content=json.dumps(
                {
                    "decision": "PASS",
                    "summary": "The candidate is consistent with the supplied facts.",
                    "issues": [],
                    "recommendations": ["Keep final approval with the change authority."],
                }
            )
        )


class _AlwaysReviseReviewLLM:
    """Return REVISE on every review to exercise the bounded graph loop."""

    def __init__(self) -> None:
        self.call_count = 0

    def invoke_with_tools(
        self,
        *,
        messages: Sequence[BaseMessage],
        tools: Sequence[BaseTool],
    ) -> AIMessage:
        self.call_count += 1
        assert messages
        assert tools
        return AIMessage(
            content=json.dumps(
                {
                    "decision": "REVISE",
                    "summary": "The candidate needs a more explicit qualification gate.",
                    "issues": ["Alternative qualification handling is not explicit enough."],
                    "recommendations": ["Add a qualification checkpoint before substitution."],
                }
            )
        )


def _require_backends() -> None:
    try:
        get_driver().verify_connectivity()
    except (Neo4jError, OSError) as exc:  # pragma: no cover - environment
        pytest.skip(f"Neo4j is not reachable: {exc}")
    try:
        with create_session() as session:
            session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:  # pragma: no cover - environment
        close_driver()
        pytest.skip(f"PostgreSQL is not reachable: {exc}")


def _request(suffix: str) -> SupplierEOLChangeCaseInput:
    return SupplierEOLChangeCaseInput(
        case_number=f"CASE-WF-{suffix}",
        ecr_number=f"ECR-WF-{suffix}",
        idempotency_key=f"test:supplier-eol-workflow:{suffix}",
        supplier_code="SUP-001",
        supplier_name="MotionWorks",
        part_number="BRG-6204-A",
        revision_code="A",
        last_time_buy_date=date(2026, 11, 30),
        eol_date=date(2027, 1, 31),
        as_of_date=date(2026, 9, 20),
        requested_by="workflow-integration-test",
        created_by="workflow-integration-test",
    )


def _cleanup(state: SupplierEOLWorkflowState | None) -> None:
    close_driver()
    if state is not None and state.impact_id is not None:
        with create_session() as session:
            if state.run_id is not None:
                session.execute(
                    delete(AuditEvent).where(AuditEvent.run_id == state.run_id)
                )
                session.execute(delete(ToolCall).where(ToolCall.run_id == state.run_id))
                session.execute(delete(AgentStep).where(AgentStep.run_id == state.run_id))
                session.execute(delete(AgentRun).where(AgentRun.run_id == state.run_id))
            strategy_ids = list(
                session.scalars(
                    select(ChangeStrategy.strategy_id).where(
                        ChangeStrategy.ecr_id == state.ecr_id
                    )
                )
            )
            eco_ids = list(
                session.scalars(
                    select(EngineeringChangeOrder.eco_id).where(
                        EngineeringChangeOrder.ecr_id == state.ecr_id
                    )
                )
            )
            if eco_ids:
                session.execute(
                    delete(ExecutionJob).where(ExecutionJob.eco_id.in_(eco_ids))
                )
                session.execute(
                    delete(EngineeringChangeOrder).where(
                        EngineeringChangeOrder.eco_id.in_(eco_ids)
                    )
                )
            if strategy_ids:
                session.execute(
                    delete(ChangeStrategyAction).where(
                        ChangeStrategyAction.strategy_id.in_(strategy_ids)
                    )
                )
                session.execute(
                    delete(ChangeStrategy).where(
                        ChangeStrategy.strategy_id.in_(strategy_ids)
                    )
                )
            session.execute(
                delete(ChangeImpact).where(ChangeImpact.impact_id == state.impact_id)
            )
            session.execute(
                delete(EngineeringChangeRequest).where(
                    EngineeringChangeRequest.ecr_id == state.ecr_id
                )
            )
            session.execute(delete(ChangeCase).where(ChangeCase.case_id == state.case_id))
            session.commit()


def test_approve_resumes_interrupted_workflow_with_same_thread():
    """A PASS review pauses and APPROVE resumes the checkpointed thread."""
    _require_backends()
    suffix = uuid.uuid4().hex[:12]
    state = None
    checkpointer = InMemorySaver()
    thread_id = f"approve-{suffix}"
    strategy_llm = _FakeStrategyLLM()
    review_llm = _ToolThenPassReviewLLM()
    review_agent = ReviewAgent(review_llm)
    try:
        assert [tool.name for tool in get_review_tools()] == [
            "find_where_used",
            "get_inventory",
            "get_purchase_orders",
            "get_alternatives",
            "get_bom_structure",
        ]
        assert build_supplier_eol_workflow(
            strategy_agent=StrategyAgent(strategy_llm),
            review_agent=review_agent,
            checkpointer=checkpointer,
        ) is not None
        try:
            interrupted = run_supplier_eol_workflow(
                _request(suffix),
                thread_id=thread_id,
                strategy_agent=StrategyAgent(strategy_llm),
                review_agent=review_agent,
                checkpointer=checkpointer,
            )
        except EntityNotFoundError as exc:  # pragma: no cover - seed dependent
            pytest.skip(f"golden seed is not loaded: {exc}")

        state = interrupted.state
        assert interrupted.status is WorkflowRunStatus.INTERRUPTED
        assert interrupted.thread_id == thread_id
        assert interrupted.interrupt_id is not None
        assert interrupted.approval_request is not None
        assert interrupted.approval_request.case_number == _request(suffix).case_number
        assert interrupted.state.approval is None
        assert interrupted.state.approval_status == "PENDING"

        completed = resume_supplier_eol_workflow(
            thread_id=thread_id,
            approval=HumanApproval(
                decision="APPROVE",
                comment="Proceed to the next controlled stage.",
                reviewer="integration-reviewer",
            ),
            checkpointer=checkpointer,
        )
        state = completed.state
        assert completed.status is WorkflowRunStatus.COMPLETED
        assert completed.approval_request is None
        assert state.approval is not None
        assert state.approval.decision == "APPROVE"
        assert state.approval_status == "COMPLETED"
        assert state.execution_status == "COMPLETED"
        assert state.execution_result is not None
        assert state.execution_result.status == "PENDING"
        assert len(state.execution_result.execution_job_ids) == 4
        assert state.run_id is not None
        assert state.status is SupplierEOLWorkflowStatus.COMPLETED
        assert state.strategy_status is StrategyGenerationStatus.COMPLETED
        assert state.review_status is ReviewStatus.COMPLETED
        assert state.review_result is not None
        assert state.review_result.decision == "PASS"
        assert state.revision_count == 0
        assert strategy_llm.call_count == 1
        assert review_llm.call_count == 2
        assert review_llm.received_tool_message

        with create_session() as session:
            case = session.get(ChangeCase, state.case_id)
            ecr = session.get(EngineeringChangeRequest, state.ecr_id)
            impact = session.get(ChangeImpact, state.impact_id)
            strategy = session.get(ChangeStrategy, state.execution_result.strategy_id)
            eco = session.get(EngineeringChangeOrder, state.execution_result.eco_id)
            job = session.get(
                ExecutionJob, state.execution_result.execution_job_ids[0]
            )
            actions = list(
                session.scalars(
                    select(ChangeStrategyAction).where(
                        ChangeStrategyAction.strategy_id
                        == state.execution_result.strategy_id
                    )
                )
            )
            assert case is not None
            assert ecr is not None and ecr.case_id == case.case_id
            assert impact is not None and impact.ecr_id == ecr.ecr_id
            assert strategy is not None and strategy.ecr_id == ecr.ecr_id
            assert strategy.status == "SELECTED"
            assert len(actions) == len(state.strategies[0].actions)
            assert eco is not None and eco.selected_strategy_id == strategy.strategy_id
            assert eco.status == "DRAFT"
            assert job is not None and job.eco_id == eco.eco_id
            assert job.status == "PENDING"

            agent_run = session.get(AgentRun, state.run_id)
            steps = list(
                session.scalars(
                    select(AgentStep).where(AgentStep.run_id == state.run_id)
                )
            )
            tool_calls = list(
                session.scalars(
                    select(ToolCall).where(ToolCall.run_id == state.run_id)
                )
            )
            audit_actions = set(
                session.scalars(
                    select(AuditEvent.action).where(AuditEvent.run_id == state.run_id)
                )
            )
            assert agent_run is not None
            assert agent_run.case_id == state.case_id
            assert agent_run.status == "SUCCEEDED"
            assert agent_run.finished_at is not None
            step_names = {step.node_name for step in steps}
            assert {
                "impact_analysis",
                "strategy_generation",
                "review",
                "human_approval",
                "execution",
            } <= step_names
            assert any(
                step.node_name == "human_approval" and step.status == "WAITING_HUMAN"
                for step in steps
            )
            assert any(
                step.node_name == "human_approval" and step.status == "SUCCEEDED"
                for step in steps
            )
            assert len(tool_calls) >= 1
            assert tool_calls[0].tool_name == "get_alternatives"
            assert tool_calls[0].status == "SUCCEEDED"
            assert tool_calls[0].step_id is not None
            assert {
                "CHANGE_CASE_CREATED",
                "HUMAN_APPROVE",
                "STRATEGY_SELECTED",
                "ECO_CREATED",
                "EXECUTION_JOB_CREATED",
            } <= audit_actions

        payload = json.loads(state.model_dump_json())
        assert payload["impact"]["part_number"] == "BRG-6204-A"
        assert payload["review_result"]["decision"] == "PASS"
        assert payload["approval"]["decision"] == "APPROVE"
        assert payload["execution_result"]["status"] == "PENDING"
    finally:
        _cleanup(state)


def test_revise_routes_to_strategy_and_stops_at_revision_limit():
    """Two revisions are generated before a third REVISE review ends the graph."""
    _require_backends()
    suffix = uuid.uuid4().hex[:12]
    state = None
    checkpointer = InMemorySaver()
    strategy_llm = _FakeStrategyLLM()
    review_llm = _AlwaysReviseReviewLLM()
    try:
        try:
            completed = run_supplier_eol_workflow(
                _request(suffix),
                thread_id=f"revision-limit-{suffix}",
                strategy_agent=StrategyAgent(strategy_llm),
                review_agent=ReviewAgent(review_llm),
                checkpointer=checkpointer,
            )
            state = completed.state
        except EntityNotFoundError as exc:  # pragma: no cover - seed dependent
            pytest.skip(f"golden seed is not loaded: {exc}")

        assert state.review_result is not None
        assert completed.status is WorkflowRunStatus.COMPLETED
        assert state.review_result.decision == "REVISE"
        assert state.revision_count == 2
        assert strategy_llm.call_count == 3
        assert strategy_llm.feedback_call_count == 2
        assert review_llm.call_count == 3
        assert json.loads(state.model_dump_json())["revision_count"] == 2
    finally:
        _cleanup(state)


def test_reject_resumes_interrupted_workflow_with_same_thread():
    """A PASS review pauses and REJECT ends the same checkpointed thread."""
    _require_backends()
    suffix = uuid.uuid4().hex[:12]
    state = None
    checkpointer = InMemorySaver()
    thread_id = f"reject-{suffix}"
    strategy_llm = _FakeStrategyLLM()
    review_llm = _ToolThenPassReviewLLM()
    try:
        try:
            interrupted = run_supplier_eol_workflow(
                _request(suffix),
                thread_id=thread_id,
                strategy_agent=StrategyAgent(strategy_llm),
                review_agent=ReviewAgent(review_llm),
                checkpointer=checkpointer,
            )
        except EntityNotFoundError as exc:  # pragma: no cover - seed dependent
            pytest.skip(f"golden seed is not loaded: {exc}")

        state = interrupted.state
        assert interrupted.status is WorkflowRunStatus.INTERRUPTED
        assert interrupted.approval_request is not None

        completed = resume_supplier_eol_workflow(
            thread_id=thread_id,
            approval=HumanApproval(
                decision="REJECT",
                comment="Do not proceed with these candidates.",
                reviewer="integration-reviewer",
            ),
            checkpointer=checkpointer,
        )
        state = completed.state
        assert completed.status is WorkflowRunStatus.COMPLETED
        assert state.approval is not None
        assert state.approval.decision == "REJECT"
        assert state.approval_status == "COMPLETED"
        assert state.execution_result is None
        assert state.execution_status == "NOT_STARTED"
        assert state.run_id is not None
        with create_session() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ChangeStrategy)
                    .where(ChangeStrategy.ecr_id == state.ecr_id)
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(EngineeringChangeOrder)
                    .where(EngineeringChangeOrder.ecr_id == state.ecr_id)
                )
                == 0
            )
            agent_run = session.get(AgentRun, state.run_id)
            step_names = set(
                session.scalars(
                    select(AgentStep.node_name).where(AgentStep.run_id == state.run_id)
                )
            )
            audit_actions = set(
                session.scalars(
                    select(AuditEvent.action).where(AuditEvent.run_id == state.run_id)
                )
            )
            assert agent_run is not None and agent_run.status == "SUCCEEDED"
            assert "execution" not in step_names
            assert "HUMAN_REJECT" in audit_actions
            assert "STRATEGY_SELECTED" not in audit_actions
            assert "ECO_CREATED" not in audit_actions
            assert "EXECUTION_JOB_CREATED" not in audit_actions
        assert json.loads(state.model_dump_json())["approval"]["decision"] == "REJECT"
    finally:
        _cleanup(state)
