"""HTTP acceptance tests for the minimal Supplier EOL API."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from neo4j.exceptions import Neo4jError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.agents.review import ReviewAgent
from app.agents.strategy import StrategyAgent
from app.api.runtime import SupplierEOLWorkflowRuntime
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
from app.main import create_app
from app.workflows.state import SupplierEOLWorkflowState


class _FakeStrategyLLM:
    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        assert system_prompt and user_prompt
        return json.dumps(
            {
                "strategies": [
                    {
                        "strategy_type": "LAST_TIME_BUY",
                        "title": "Bounded last-time buy",
                        "summary": "Evaluate a bounded purchase against confirmed demand.",
                        "rationale": "The supplier notice contains a last-time-buy window.",
                        "actions": ["Validate demand horizon"],
                        "risks": ["Planned inbound may arrive late"],
                    }
                ]
            }
        )


class _FakeReviewLLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_with_tools(
        self,
        *,
        messages: Sequence[BaseMessage],
        tools: Sequence[BaseTool],
    ) -> AIMessage:
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_alternatives",
                        "args": {
                            "part_number": "BRG-6204-A",
                            "revision_code": "A",
                        },
                        "id": "api-review-tool-call",
                        "type": "tool_call",
                    }
                ],
            )
        assert tools and isinstance(messages[-1], ToolMessage)
        return AIMessage(
            content=json.dumps(
                {
                    "decision": "PASS",
                    "summary": "The strategy is grounded in the supplied facts.",
                    "issues": [],
                    "recommendations": ["Retain human approval."],
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


def _client() -> TestClient:
    runtime = SupplierEOLWorkflowRuntime(
        checkpointer=InMemorySaver(),
        strategy_agent_factory=lambda: StrategyAgent(_FakeStrategyLLM()),
        review_agent_factory=lambda: ReviewAgent(_FakeReviewLLM()),
    )
    return TestClient(create_app(runtime))


def _start_payload(thread_id: str) -> dict[str, object]:
    return {
        "thread_id": thread_id,
        "part_number": "BRG-6204-A",
        "revision": "A",
        "supplier_code": "SUP-001",
        "supplier_name": "MotionWorks",
        "last_time_buy_date": "2026-11-30",
        "eol_date": "2027-01-31",
        "as_of_date": "2026-09-20",
        "requested_by": "api-integration-test",
    }


def _cleanup(state: SupplierEOLWorkflowState | None) -> None:
    close_driver()
    if state is None:
        return
    with create_session() as session:
        if state.run_id is not None:
            session.execute(delete(AuditEvent).where(AuditEvent.run_id == state.run_id))
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
            session.execute(delete(ExecutionJob).where(ExecutionJob.eco_id.in_(eco_ids)))
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
                delete(ChangeStrategy).where(ChangeStrategy.strategy_id.in_(strategy_ids))
            )
        if state.impact_id is not None:
            session.execute(
                delete(ChangeImpact).where(ChangeImpact.impact_id == state.impact_id)
            )
        if state.ecr_id is not None:
            session.execute(
                delete(EngineeringChangeRequest).where(
                    EngineeringChangeRequest.ecr_id == state.ecr_id
                )
            )
        if state.case_id is not None:
            session.execute(delete(ChangeCase).where(ChangeCase.case_id == state.case_id))
        session.commit()


def test_health_and_unknown_thread():
    client = _client()
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/workflows/supplier-eol/missing").status_code == 404


def test_start_query_and_approve_resume_to_execution():
    _require_backends()
    client = _client()
    thread_id = f"api-approve-{uuid.uuid4().hex[:10]}"
    state = None
    try:
        started = client.post(
            "/api/v1/workflows/supplier-eol",
            json=_start_payload(thread_id),
        )
        assert started.status_code == 200
        started_payload = started.json()
        state = SupplierEOLWorkflowState.model_validate(started_payload["state"])
        assert started_payload["status"] == "INTERRUPTED"
        assert started_payload["thread_id"] == thread_id
        assert started_payload["state"]["run_id"]
        assert started_payload["approval_request"] is not None

        queried = client.get(f"/api/v1/workflows/supplier-eol/{thread_id}")
        assert queried.status_code == 200
        assert queried.json()["status"] == "INTERRUPTED"

        approved = client.post(
            f"/api/v1/workflows/supplier-eol/{thread_id}/approval",
            json={
                "decision": "APPROVE",
                "comment": "Approved by API test",
                "reviewer": "api-reviewer",
                "selected_strategy_index": 0,
            },
        )
        assert approved.status_code == 200
        payload = approved.json()
        state = SupplierEOLWorkflowState.model_validate(payload["state"])
        assert payload["status"] == "COMPLETED"
        assert payload["state"]["approval"]["decision"] == "APPROVE"
        assert payload["state"]["execution_result"] is not None
    finally:
        _cleanup(state)


def test_reject_completes_without_execution():
    _require_backends()
    client = _client()
    thread_id = f"api-reject-{uuid.uuid4().hex[:10]}"
    state = None
    try:
        started = client.post(
            "/api/v1/workflows/supplier-eol",
            json=_start_payload(thread_id),
        )
        assert started.status_code == 200
        state = SupplierEOLWorkflowState.model_validate(started.json()["state"])

        rejected = client.post(
            f"/api/v1/workflows/supplier-eol/{thread_id}/approval",
            json={
                "decision": "REJECT",
                "comment": "Rejected by API test",
                "reviewer": "api-reviewer",
            },
        )
        assert rejected.status_code == 200
        payload = rejected.json()
        state = SupplierEOLWorkflowState.model_validate(payload["state"])
        assert payload["status"] == "COMPLETED"
        assert payload["state"]["approval"]["decision"] == "REJECT"
        assert payload["state"]["execution_result"] is None
    finally:
        _cleanup(state)
