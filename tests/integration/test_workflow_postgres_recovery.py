"""Durable approval recovery with a fresh saver and HTTP runtime."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from sqlalchemy import delete, func, select, text

from app.agents.review import ReviewAgent
from app.agents.strategy import StrategyAgent
from app.api.runtime import MaterialSubstitutionRuntime, SupplierEOLWorkflowRuntime
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
from app.domain.dto.material_substitution import MaterialSubstitutionWorkflowState
from app.main import create_app
from app.services.execution import ExecutionService
from app.workflows.postgres_checkpoint import create_postgres_checkpointer
from app.workflows.state import SupplierEOLWorkflowState


class _StrategyLLM:
    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        strategy_type = (
            "LAST_TIME_BUY" if "last-time-buy" in user_prompt.lower()
            else "QUALIFIED_ALTERNATIVE"
        )
        return json.dumps({"strategies": [{
            "strategy_type": strategy_type, "title": "受控处置",
            "summary": "核对事实后由人工批准执行。", "rationale": "依据现有影响分析。",
            "actions": ["核对物料需求"], "risks": ["交期变化"],
        }]}, ensure_ascii=False)


class _ReviewLLM:
    def __init__(self, decisions: tuple[str, ...] = ("PASS",)) -> None:
        self.decisions = decisions
        self.calls = 0

    def invoke_with_tools(
        self, *, messages: Sequence[BaseMessage], tools: Sequence[BaseTool]
    ) -> AIMessage:
        decision = self.decisions[min(self.calls, len(self.decisions) - 1)]
        self.calls += 1
        return AIMessage(content=json.dumps({
            "decision": decision, "summary": "事实与策略一致" if decision == "PASS" else "策略仍有风险",
            "issues": [] if decision == "PASS" else ["应核验替代方案的实施风险"],
            "recommendations": [] if decision == "PASS" else ["明确风险后由人工决定"],
        }, ensure_ascii=False))


def _client(kind: str, saver: object, *, fake_llm: bool,
            review_llm: _ReviewLLM | None = None) -> TestClient:
    kwargs = {
        "checkpointer": saver,
        "strategy_agent_factory": (lambda: StrategyAgent(_StrategyLLM())) if fake_llm else None,
        "review_agent_factory": (lambda: ReviewAgent(review_llm or _ReviewLLM())) if fake_llm else None,
    }
    if kind == "supplier_eol":
        return TestClient(create_app(runtime=SupplierEOLWorkflowRuntime(**kwargs)))
    return TestClient(create_app(material_runtime=MaterialSubstitutionRuntime(**kwargs)))


def _cleanup(kind: str, thread_id: str, state: dict[str, object] | None) -> None:
    # Exact, test-owned thread only; checkpoint data is distinct from ECM data.
    internal_id = f"{kind}:{thread_id}"
    with create_session() as session:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            session.execute(text(f"DELETE FROM {table} WHERE thread_id = :id"), {"id": internal_id})
        if state is not None:
            run_id = uuid.UUID(str(state["run_id"]))
            case_id = uuid.UUID(str(state["case_id"]))
            ecr_id = uuid.UUID(str(state["ecr_id"]))
            session.execute(delete(AuditEvent).where(AuditEvent.run_id == run_id))
            session.execute(delete(ToolCall).where(ToolCall.run_id == run_id))
            session.execute(delete(AgentStep).where(AgentStep.run_id == run_id))
            session.execute(delete(AgentRun).where(AgentRun.run_id == run_id))
            strategies = list(session.scalars(select(ChangeStrategy.strategy_id).where(
                ChangeStrategy.ecr_id == ecr_id,
            )))
            ecos = list(session.scalars(select(EngineeringChangeOrder.eco_id).where(
                EngineeringChangeOrder.ecr_id == ecr_id,
            )))
            if ecos:
                session.execute(delete(ExecutionJob).where(ExecutionJob.eco_id.in_(ecos)))
                session.execute(delete(EngineeringChangeOrder).where(
                    EngineeringChangeOrder.eco_id.in_(ecos),
                ))
            if strategies:
                session.execute(delete(ChangeStrategyAction).where(
                    ChangeStrategyAction.strategy_id.in_(strategies),
                ))
                session.execute(delete(ChangeStrategy).where(
                    ChangeStrategy.strategy_id.in_(strategies),
                ))
            session.execute(delete(ChangeImpact).where(ChangeImpact.ecr_id == ecr_id))
            session.execute(delete(EngineeringChangeRequest).where(
                EngineeringChangeRequest.ecr_id == ecr_id,
            ))
            session.execute(delete(ChangeCase).where(ChangeCase.case_id == case_id))
        session.commit()


@pytest.mark.parametrize("kind,decision", [
    ("supplier_eol", "APPROVE"),
    ("supplier_eol", "REJECT"),
    ("material_substitution", "APPROVE"),
    ("material_substitution", "REJECT"),
])
def test_restart_recovery_and_single_approval(kind: str, decision: str) -> None:
    thread_id = f"durable-{uuid.uuid4().hex[:12]}"
    path = f"/api/v1/workflows/{'supplier-eol' if kind == 'supplier_eol' else 'material-substitution'}"
    payload: dict[str, object] = {
        "thread_id": thread_id, "part_number": "BRG-6204-A",
        "as_of_date": "2026-09-20",
    }
    if kind == "supplier_eol":
        payload.update({
            "revision": "A", "supplier_code": "SUP-001", "supplier_name": "MotionWorks",
            "last_time_buy_date": "2026-11-30", "eol_date": "2027-01-31",
        })
    else:
        payload.update({"revision_code": "A", "candidate_part_number": "BRG-6204-B"})
    state = None
    try:
        saver1, pool1 = create_postgres_checkpointer()
        try:
            client1 = _client(kind, saver1, fake_llm=True)
            started = client1.post(path, json=payload)
            assert started.status_code == 200, started.text
            assert started.json()["status"] == "INTERRUPTED"
            state = started.json()["state"]
            assert started.json()["approval_request"]
            assert state["review_count"] == 1
            assert state["review_exhausted"] is False
            assert state["review_result"]["decision"] == "PASS"
            assert client1.post(path, json=payload).status_code == 409
        finally:
            pool1.close()

        # Simulate process restart: new saver, pool, app and runtime; no in-memory state.
        saver2, pool2 = create_postgres_checkpointer()
        try:
            client2 = _client(kind, saver2, fake_llm=False)
            pending = client2.get(f"{path}/{thread_id}")
            assert pending.status_code == 200, pending.text
            assert pending.json()["status"] == "INTERRUPTED"
            assert pending.json()["state"]["run_id"] == state["run_id"]
            assert client2.post(path, json=payload).status_code == 409
            with create_session() as session:
                assert session.scalar(select(AgentRun.status).where(
                    AgentRun.run_id == uuid.UUID(str(state["run_id"])),
                )) == "WAITING_HUMAN"
            paused_detail = client2.get(f"/api/v1/agent-runs/{state['run_id']}")
            assert paused_detail.status_code == 200
            assert paused_detail.json()["status"] == "WAITING_HUMAN"
            assert paused_detail.json()["finished_at"] is None

            approved = client2.post(f"{path}/{thread_id}/approval", json={
                "decision": decision, "comment": "durable test", "reviewer": "qa",
            })
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "COMPLETED"
            state = approved.json()["state"]
            assert state["approval"]["decision"] == decision
            assert bool(state["execution_result"]) == (decision == "APPROVE")
            listed = client2.get("/api/v1/agent-runs")
            assert listed.status_code == 200
            assert any(row["run_id"] == state["run_id"] for row in listed.json())
            observed = client2.get(f"/api/v1/agent-runs/{state['run_id']}")
            assert observed.status_code == 200, observed.text
            detail = observed.json()
            assert detail["thread_id"] == thread_id
            assert detail["status"] == "SUCCEEDED"
            assert any(step["node_name"] == "human_approval" for step in detail["steps"])
            assert len(detail["execution_jobs"]) == (4 if decision == "APPROVE" else 0)
            if decision == "APPROVE":
                assert {"PURCHASE_ACTION", "PRODUCTION_ACTION"} <= {
                    job["action_type"] for job in detail["execution_jobs"]
                }
                assert any(event["action"] == "ECO_CREATED" for event in detail["audit_events"])
                assert sum(event["action"] == "EXECUTION_JOB_CREATED"
                           for event in detail["audit_events"]) == 4
            else:
                assert not any(step["node_name"] == "execution" for step in detail["steps"])
                assert any(event["action"] == "HUMAN_REJECT" for event in detail["audit_events"])
            if decision == "APPROVE":
                saved = (SupplierEOLWorkflowState if kind == "supplier_eol"
                         else MaterialSubstitutionWorkflowState).model_validate(state)
                service = ExecutionService()
                if kind == "supplier_eol":
                    repeated = service.execute_approved_strategy(
                        ecr_id=saved.ecr_id, event=saved.input_event,
                        strategy=saved.strategies[0], approval=saved.approval,
                    )
                else:
                    repeated = service.execute_approved_substitution(
                        ecr_id=saved.ecr_id, event=saved.input_event,
                        candidate_revision_code=saved.impact.candidate_revision_code,
                        strategy=saved.strategies[0], approval=saved.approval,
                    )
                assert str(repeated.eco_id) == state["execution_result"]["eco_id"]
            assert client2.post(f"{path}/{thread_id}/approval", json={
                "decision": decision, "comment": "duplicate", "reviewer": "qa",
            }).status_code == 409
            with create_session() as session:
                run_id = uuid.UUID(str(state["run_id"]))
                ecr_id = uuid.UUID(str(state["ecr_id"]))
                assert session.scalar(select(AgentRun.status).where(
                    AgentRun.run_id == run_id,
                )) == "SUCCEEDED"
                assert session.scalar(select(func.count()).select_from(AgentRun).where(
                    AgentRun.run_id == run_id,
                )) == 1
                assert session.scalar(select(func.count()).select_from(ChangeCase).where(
                    ChangeCase.case_id == uuid.UUID(str(state["case_id"])),
                )) == 1
                expected = 1 if decision == "APPROVE" else 0
                assert session.scalar(select(func.count()).select_from(EngineeringChangeOrder).where(
                    EngineeringChangeOrder.ecr_id == ecr_id,
                )) == expected
                if decision == "APPROVE":
                    jobs = list(session.scalars(select(ExecutionJob).where(
                        ExecutionJob.eco_id == uuid.UUID(str(state["execution_result"]["eco_id"])),
                    )))
                    assert len(jobs) == 4
                    assert len({job.action_type for job in jobs}) == 4
                    assert all(job.payload["case_id"] == state["case_id"] for job in jobs)
                    assert all(job.payload["ecr_id"] == state["ecr_id"] for job in jobs)
                    assert all(job.payload["owner_department"] for job in jobs)
                    assert all(job.payload["execution_mode"] == "CONTROLLED_RECORD_ONLY"
                               for job in jobs)
        finally:
            pool2.close()
    finally:
        _cleanup(kind, thread_id, state)


@pytest.mark.parametrize("kind", ["supplier_eol", "material_substitution"])
@pytest.mark.parametrize("reviews,decision", [
    (("REVISE", "PASS"), "REJECT"),
    (("REVISE", "REVISE"), "APPROVE"),
    (("REVISE", "REVISE"), "REJECT"),
])
def test_review_limit_interrupt_restart_and_human_decision(
    kind: str, reviews: tuple[str, ...], decision: str,
) -> None:
    thread_id = f"review-human-{uuid.uuid4().hex[:12]}"
    path = f"/api/v1/workflows/{'supplier-eol' if kind == 'supplier_eol' else 'material-substitution'}"
    payload: dict[str, object] = {
        "thread_id": thread_id, "part_number": "BRG-6204-A", "as_of_date": "2026-09-20",
    }
    if kind == "supplier_eol":
        payload.update({
            "revision": "A", "supplier_code": "SUP-001", "supplier_name": "MotionWorks",
            "last_time_buy_date": "2026-11-30", "eol_date": "2027-01-31",
        })
    else:
        payload.update({"revision_code": "A", "candidate_part_number": "BRG-6204-B"})
    state = None
    review_llm = _ReviewLLM(reviews)
    try:
        saver1, pool1 = create_postgres_checkpointer()
        try:
            started = _client(kind, saver1, fake_llm=True, review_llm=review_llm).post(
                path, json=payload,
            )
            assert started.status_code == 200, started.text
            body = started.json()
            state = body["state"]
            assert body["status"] == "INTERRUPTED"
            assert review_llm.calls == 2
            assert state["review_count"] == 2
            assert state["revision_count"] == 1
            assert state["review_result"]["decision"] == reviews[-1]
            assert state["review_exhausted"] is (reviews[-1] == "REVISE")
            assert body["approval_request"]["review_exhausted"] is state["review_exhausted"]
            assert bool(body["approval_request"]["human_intervention_reason"]) is state["review_exhausted"]
            assert state["approval"] is None and state["execution_result"] is None
            with create_session() as session:
                assert session.scalar(select(AgentRun.status).where(
                    AgentRun.run_id == uuid.UUID(state["run_id"]),
                )) == "WAITING_HUMAN"
        finally:
            pool1.close()

        saver2, pool2 = create_postgres_checkpointer()
        try:
            client = _client(kind, saver2, fake_llm=False)
            restored = client.get(f"{path}/{thread_id}")
            assert restored.status_code == 200, restored.text
            assert restored.json()["status"] == "INTERRUPTED"
            assert restored.json()["state"]["run_id"] == state["run_id"]
            response = client.post(f"{path}/{thread_id}/approval", json={
                "decision": decision, "comment": "知悉评审风险并作出人工决定", "reviewer": "qa",
            })
            assert response.status_code == 200, response.text
            state = response.json()["state"]
            assert response.json()["status"] == "COMPLETED"
            assert state["review_result"]["decision"] == reviews[-1]
            assert state["approval"]["decision"] == decision
            assert bool(state["execution_result"]) is (decision == "APPROVE")
            assert client.post(f"{path}/{thread_id}/approval", json={
                "decision": decision, "reviewer": "qa",
            }).status_code == 409
            with create_session() as session:
                run_id = uuid.UUID(state["run_id"])
                ecr_id = uuid.UUID(state["ecr_id"])
                assert session.scalar(select(AgentRun.status).where(AgentRun.run_id == run_id)) == "SUCCEEDED"
                assert session.scalar(select(func.count()).select_from(ChangeCase).where(
                    ChangeCase.case_id == uuid.UUID(state["case_id"]),
                )) == 1
                assert session.scalar(select(func.count()).select_from(EngineeringChangeOrder).where(
                    EngineeringChangeOrder.ecr_id == ecr_id,
                )) == (1 if decision == "APPROVE" else 0)
                if decision == "APPROVE":
                    assert session.scalar(select(func.count()).select_from(ExecutionJob).where(
                        ExecutionJob.eco_id == uuid.UUID(state["execution_result"]["eco_id"]),
                    )) == 4
                events = list(session.scalars(select(AuditEvent).where(AuditEvent.run_id == run_id)))
                human = next(event for event in events if event.action == f"HUMAN_{decision}")
                assert human.event_metadata["review_decision"] == reviews[-1]
                assert human.event_metadata["review_exhausted"] is state["review_exhausted"]
                assert human.event_metadata["review_risk_accepted"] is (
                    reviews[-1] == "REVISE" and decision == "APPROVE"
                )
                if decision == "REJECT":
                    assert not any(event.action == "EXECUTION_JOB_CREATED" for event in events)
                else:
                    assert any(event.action == "EXECUTION_JOB_CREATED" for event in events)
        finally:
            pool2.close()
    finally:
        _cleanup(kind, thread_id, state)


@pytest.mark.parametrize("kind", ["supplier_eol", "material_substitution"])
def test_missing_checkpoint_and_unavailable_pool(kind: str) -> None:
    path = f"/api/v1/workflows/{'supplier-eol' if kind == 'supplier_eol' else 'material-substitution'}"
    saver, pool = create_postgres_checkpointer()
    client = _client(kind, saver, fake_llm=False)
    assert client.get(f"{path}/missing-{uuid.uuid4().hex}").status_code == 404
    pool.close()
    response = client.get(f"{path}/missing-{uuid.uuid4().hex}")
    assert response.status_code == 503
    assert "状态存储" in response.json()["detail"]


@pytest.mark.skipif(
    os.getenv("CHANGEPILOT_REAL_REVIEW_SMOKE") != "1",
    reason="explicit real DeepSeek smoke only",
)
def test_real_deepseek_supplier_eol_reaches_human_gate() -> None:
    thread_id = f"real-review-{uuid.uuid4().hex[:12]}"
    path = "/api/v1/workflows/supplier-eol"
    state = None
    saver, pool = create_postgres_checkpointer()
    try:
        client = _client("supplier_eol", saver, fake_llm=False)
        response = client.post(path, json={
            "thread_id": thread_id, "part_number": "BRG-6204-A", "revision": "A",
            "supplier_code": "SUP-001", "supplier_name": "MotionWorks",
            "last_time_buy_date": "2026-11-30", "eol_date": "2027-01-31",
            "as_of_date": "2026-09-20",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        state = body["state"]
        print(f"DeepSeek review={state['review_result']['decision']}; "
              f"rounds={state['review_count']}; exhausted={state['review_exhausted']}; "
              f"status={body['status']}")
        assert body["status"] == "INTERRUPTED"
        assert body["approval_request"] is not None
        assert state["approval"] is None and state["execution_result"] is None
        ended = client.post(f"{path}/{thread_id}/approval", json={
            "decision": "REJECT", "comment": "smoke test cleanup", "reviewer": "qa",
        })
        assert ended.status_code == 200, ended.text
        state = ended.json()["state"]
        assert state["approval"]["decision"] == "REJECT"
    finally:
        pool.close()
        _cleanup("supplier_eol", thread_id, state)


@pytest.mark.skipif(
    os.getenv("CHANGEPILOT_REAL_MATERIAL_CHINESE_SMOKE") != "1",
    reason="explicit real DeepSeek Chinese smoke only",
)
def test_real_deepseek_material_substitution_chinese() -> None:
    thread_id = f"real-material-zh-{uuid.uuid4().hex[:12]}"
    path = "/api/v1/workflows/material-substitution"
    state = None
    saver, pool = create_postgres_checkpointer()
    try:
        client = _client("material_substitution", saver, fake_llm=False)
        response = client.post(path, json={
            "thread_id": thread_id, "part_number": "BRG-6204-A", "revision_code": "A",
            "candidate_part_number": "BRG-6204-B", "as_of_date": "2026-09-20",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        state = body["state"]
        assert body["status"] == "INTERRUPTED"
        assert state["strategies"] and state["review_result"]
        for strategy in state["strategies"]:
            for field in ("title", "summary", "rationale"):
                assert re.search(r"[\u4e00-\u9fff]", strategy[field]), (field, strategy[field])
            for field in ("actions", "risks"):
                assert all(re.search(r"[\u4e00-\u9fff]", item) for item in strategy[field])
        review = state["review_result"]
        assert re.search(r"[\u4e00-\u9fff]", review["summary"]), review["summary"]
        assert all(re.search(r"[\u4e00-\u9fff]", item)
                   for field in ("issues", "recommendations") for item in review[field])
        print(json.dumps({
            "strategy_count": len(state["strategies"]),
            "review_decision": review["decision"],
            "strategy_title": state["strategies"][0]["title"],
            "review_summary": review["summary"],
        }, ensure_ascii=False))
        ended = client.post(f"{path}/{thread_id}/approval", json={
            "decision": "REJECT", "comment": "smoke test cleanup", "reviewer": "qa",
        })
        assert ended.status_code == 200, ended.text
        state = ended.json()["state"]
    finally:
        pool.close()
        _cleanup("material_substitution", thread_id, state)
