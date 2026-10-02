"""Focused release-candidate regressions against the local Golden Seed."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import delete, select

from app.agents.enterprise_assistant import EnterpriseAssistant
from app.db.postgres.models.agent import AgentRun, AgentStep, ToolCall
from app.db.postgres.models.assistant import AssistantConversation, AssistantMessage
from app.db.postgres.models.audit import AuditEvent
from app.db.postgres.session import create_session
from app.llm.client import DeepSeekLLMClient
from app.main import create_app
from app.services.assistant import AssistantService
from app.services.data_center import DataCenterService
from app.services.trace import TraceService


def _run_ids() -> set[uuid.UUID]:
    with create_session() as session:
        return set(session.scalars(select(AgentRun.run_id).where(
            AgentRun.workflow_name == "enterprise_assistant",
        )))


def _cleanup(conversations: list[uuid.UUID], before: set[uuid.UUID]) -> None:
    with create_session() as session:
        for conversation_id in conversations:
            session.execute(delete(AssistantConversation).where(
                AssistantConversation.id == conversation_id,
            ))
        session.commit()
    run_ids = _run_ids() - before
    if run_ids:
        with create_session() as session:
            session.execute(delete(AuditEvent).where(AuditEvent.run_id.in_(run_ids)))
            session.execute(delete(ToolCall).where(ToolCall.run_id.in_(run_ids)))
            session.execute(delete(AgentStep).where(AgentStep.run_id.in_(run_ids)))
            session.execute(delete(AgentRun).where(AgentRun.run_id.in_(run_ids)))
            session.commit()


def test_supplier_relationship_filter_combinations() -> None:
    service = DataCenterService()
    row = service.supplier_parts()[0]
    checks = (
        service.supplier_parts(supplier=row.supplier_code),
        service.supplier_parts(supplier=row.supplier_name),
        service.supplier_parts(part_number=row.part_number),
        service.supplier_parts(supplier=row.supplier_code, part_number=row.part_number),
    )
    assert all(any(item.supplier_code == row.supplier_code and
                   item.part_number == row.part_number for item in rows) for rows in checks)
    assert all(item.supplier_code == row.supplier_code and item.part_number == row.part_number
               for item in checks[-1])


def test_supplier_relationship_http_accepts_web_selection_and_filters() -> None:
    client = TestClient(create_app())
    cases = (
        ({"supplier": "SUP-002"}, "SUP-002", None),
        ({"supplier": "GearTech"}, "SUP-002", None),
        ({"supplier": "GearTech (SUP-002)"}, "SUP-002", None),
        ({"part_number": "BRG-6204-A"}, None, "BRG-6204-A"),
        ({"supplier": "SUP-002", "part_number": "GEAR-G100"}, "SUP-002", "GEAR-G100"),
    )
    for params, supplier, part in cases:
        response = client.get("/api/v1/data/supplier-parts", params=params)
        assert response.status_code == 200
        rows = response.json()
        assert rows, params
        assert all(supplier is None or row["supplier_code"] == supplier for row in rows)
        assert all(part is None or row["part_number"] == part for row in rows)


def test_assistant_supplier_name_uses_supplier_relationship_tool() -> None:
    before = _run_ids()
    service = AssistantService()
    conversation = service.create().id
    try:
        result = service.send(conversation, "MotionWorks 供应哪些零件？")
        assert result.answer_status == "SUCCESS"
        assert result.assistant_message.metadata_json["tool_names"] == ["get_supplier_parts"]
        assert "MotionWorks" in result.assistant_message.content
    finally:
        _cleanup([conversation], before)


@pytest.mark.parametrize("question,status,fragment", [
    ("PART-NOT-EXIST 当前库存是多少？", "NO_DATA", "未查询到 PART-NOT-EXIST 的库存记录"),
    ("当前库存是多少？", "MISSING_INPUT", "请提供"),
])
def test_candidate_identity_is_not_missing_input(question: str, status: str, fragment: str) -> None:
    before = _run_ids()
    service = AssistantService()
    conversation = service.create().id
    try:
        result = service.send(conversation, question)
        assert result.answer_status == status
        assert fragment in result.assistant_message.content
    finally:
        _cleanup([conversation], before)


def test_alternative_result_focus_part_switch_and_isolation() -> None:
    before = _run_ids()
    service = AssistantService()
    first, second = service.create().id, service.create().id
    try:
        a = service.send(first, "BRG-6204-A 有哪些替代料？")
        assert a.context.last_result_type == "alternatives"
        assert {item["part_number"] for item in a.context.last_result_entities} >= {
            "BRG-6204-B", "BRG-6204-C",
        }
        assert AssistantService().get(first).context.last_result_entities == a.context.last_result_entities
        qualified = service.send(first, "其中哪个是已认证的？")
        assert "BRG-6204-B" in qualified.assistant_message.content
        assert "BRG-6204-C" not in qualified.assistant_message.content
        unqualified = service.send(first, "哪个是未认证的？")
        assert "BRG-6204-C" in unqualified.assistant_message.content
        assert "BRG-6204-B" not in unqualified.assistant_message.content
        service.send(first, "BRG-6204-A 当前库存多少？")
        switched = service.send(first, "那 BRG-6204-B 当前库存呢？")
        assert switched.context.current_part == "BRG-6204-B"
        relation = service.send(first, "它有哪些替代关系？")
        assert relation.context.current_part == "BRG-6204-B"
        back = service.send(first, "BRG-6204-A 有哪些替代料？")
        assert back.context.current_part == "BRG-6204-A"
        assert service.get(second).context.current_part is None
    finally:
        _cleanup([first, second], before)


def test_conversation_delete_keeps_run_and_audit() -> None:
    before = _run_ids()
    trace = TraceService()
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(trace_service=trace))
    conversation = service.create().id
    try:
        service.send(conversation, "BRG-6204-A 当前库存多少？")
        created_runs = _run_ids() - before
        assert created_runs
        run_id = next(iter(created_runs))
        trace.audit(
            run_id=run_id, case_id=None, actor_type="SYSTEM", actor_id="rc-test",
            action="RC_TEST_EVENT", object_type="assistant_conversation",
            object_id=str(conversation),
        )
        client = TestClient(create_app())
        assert client.delete(f"/api/v1/assistant/conversations/{conversation}").status_code == 204
        assert client.get(f"/api/v1/assistant/conversations/{conversation}").status_code == 404
        with create_session() as session:
            assert not session.scalars(select(AssistantMessage).where(
                AssistantMessage.conversation_id == conversation,
            )).all()
        assert created_runs <= _run_ids()
        with create_session() as session:
            assert session.scalars(select(AuditEvent).where(AuditEvent.run_id == run_id)).first()
            assert session.scalars(select(AgentStep).where(AgentStep.run_id == run_id)).first()
            assert session.scalars(select(ToolCall).where(ToolCall.run_id == run_id)).first()
    finally:
        _cleanup([conversation], before)


def test_browser_delete_preflight_allows_method() -> None:
    response = TestClient(create_app()).options(
        "/api/v1/assistant/conversations/00000000-0000-0000-0000-000000000000",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "DELETE",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]


def test_full_domain_fallback_still_runs_domain_agents() -> None:
    class InvalidPlanner:
        def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
            if "跨域/综合" in system_prompt:
                return '{"multi_agent":true,"agents":[{"agent_name":"Invalid","task":"x"}]}'
            return '{"judgment":"已核验事实提示后续供应连续性风险。","recommendations":["核验未完成采购订单交付。"]}'

        def invoke_with_tools(self, **kwargs: object) -> AIMessage:
            return AIMessage(content="")

    before = _run_ids()
    trace = TraceService()
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        llm_client=InvalidPlanner(), trace_service=trace,
    ))
    conversation = service.create().id
    try:
        result = service.send(conversation, "综合分析 BRG-6204-A 停产会对公司造成哪些影响？")
        assert "### 企业事实" in result.assistant_message.content
        with create_session() as session:
            steps = list(session.scalars(select(AgentStep).where(
                AgentStep.run_id.in_(_run_ids() - before),
            )))
        planned = next(step for step in steps if step.node_name == "supervisor_plan")
        assert planned.output_summary["recovery_code"] == "SUPERVISOR_PLAN_RETRY_FAILED"
        assert {step.node_name for step in steps} >= {"StructureAgent", "SupplyAgent"}
    finally:
        _cleanup([conversation], before)


@pytest.mark.skipif(os.getenv("CHANGEPILOT_REAL_RC_SMOKE") != "1", reason="explicit DeepSeek smoke only")
def test_real_full_domain_eol_smoke() -> None:
    before = _run_ids()
    trace = TraceService()
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        llm_client=DeepSeekLLMClient(), trace_service=trace,
    ))
    conversation = service.create().id
    try:
        result = service.send(conversation, "综合分析 BRG-6204-A 停产会对公司造成哪些影响？")
        assert "### 企业事实" in result.assistant_message.content
        assert result.answer_status in {"SUCCESS", "TOOL_ERROR"}
        with create_session() as session:
            names = set(session.scalars(select(AgentStep.node_name).where(
                AgentStep.run_id.in_(_run_ids() - before),
            )))
        assert "supervisor_plan" in names
        assert "SupplyAgent" in names
    finally:
        _cleanup([conversation], before)


@pytest.mark.skipif(os.getenv("CHANGEPILOT_REAL_RC_REPEAT") != "1", reason="explicit repeated DeepSeek smoke only")
@pytest.mark.parametrize("attempt", [1, 2, 3])
@pytest.mark.parametrize("scenario,question", [
    ("supply", "结合 BRG-6204-A 的库存和采购情况分析供应风险"),
    ("eol", "综合分析 BRG-6204-A 停产会对公司造成哪些影响？"),
])
def test_real_rc_repeated_scenarios(scenario: str, question: str, attempt: int) -> None:
    before = _run_ids()
    trace = TraceService()
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        llm_client=DeepSeekLLMClient(), trace_service=trace,
    ))
    conversation = service.create().id
    try:
        result = service.send(conversation, question)
        print(f"RC_REPEAT scenario={scenario} attempt={attempt} status={result.answer_status} "
              f"facts={len(result.assistant_message.metadata_json['tool_names'])}")
        with create_session() as session:
            steps = list(session.scalars(select(AgentStep).where(
                AgentStep.run_id.in_(_run_ids() - before),
            )))
            failed_tools = list(session.scalars(select(ToolCall.tool_name).where(
                ToolCall.run_id.in_(_run_ids() - before), ToolCall.status == "FAILED",
            )))
        print("RC_TRACE domain_statuses=" + str({
            step.node_name: (step.output_summary or {}).get("status")
            for step in steps if step.node_name.endswith("Agent")
        }) + " synthesis=" + str(next((step.output_summary for step in steps
                                         if step.node_name == "supervisor_summary"), None))
              + " failed_tools=" + str(failed_tools))
        assert result.answer_status in {"SUCCESS", "PARTIAL"}
        assert "### 企业事实" in result.assistant_message.content
        assert result.assistant_message.metadata_json["tool_names"]
    finally:
        _cleanup([conversation], before)
