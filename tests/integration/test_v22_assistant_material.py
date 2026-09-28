"""Focused V2.2 acceptance checks with controllable model responses."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import delete, select

from app.agents.enterprise_assistant import EnterpriseAssistant, ToolFact
from app.agents.review import ReviewAgent
from app.agents.strategy import StrategyAgent
from app.api.routes.assistant import get_assistant_service
from app.api.runtime import MaterialSubstitutionRuntime
from app.core.business_time import current_business_date, shanghai_datetime
from app.db.postgres.models.agent import AgentRun, AgentStep, ToolCall
from app.db.postgres.models.assistant import AssistantConversation, AssistantMessage
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
from app.llm.client import LLMResponseError
from app.main import create_app
from app.services.assistant import AssistantService
from app.services.trace import TraceService
from app.tools.langchain import get_enterprise_tools
from app.tools.schemas import GetAlternativesInput


class _AssistantLLM:
    def invoke_with_tools(
        self, *, messages: Sequence[BaseMessage], tools: Sequence[BaseTool]
    ) -> AIMessage:
        question = next(
            message.content for message in reversed(messages)
            if isinstance(message, HumanMessage) and not str(message.content).startswith("当前会话上下文")
        )
        assert isinstance(question, str)
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if not results:
            part = "ROB-P100" if "零件" in question and ("ROB" in question or "其中" in question) else "BRG-6204-A"
            return AIMessage(content="", tool_calls=[{
                "name": "get_part_revisions", "args": {"part_number": part},
                "id": uuid.uuid4().hex, "type": "tool_call",
            }])
        if len(results) == 1:
            if "库存" in question:
                name, args = "get_inventory", {"part_number": "BRG-6204-A", "revision_code": "A"}
            elif "替代料" in question:
                name, args = "get_alternatives", {"part_number": "BRG-6204-A", "revision_code": "A"}
            else:
                name, args = "get_bom_structure", {
                    "part_number": "ROB-P100", "revision_code": "A", "as_of_date": "2026-09-20",
                }
            return AIMessage(content="", tool_calls=[{
                "name": name, "args": args, "id": uuid.uuid4().hex, "type": "tool_call",
            }])
        data = json.loads(str(results[-1].content))
        if results[-1].name == "get_bom_structure":
            answer = f"ROB-P100 的零件与用量：{data['totals']}"
        elif results[-1].name == "get_inventory":
            answer = f"BRG-6204-A 的库存记录：{data['rows']}"
        else:
            answer = f"BRG-6204-A 的替代料：{data['rows']}"
        return AIMessage(content=answer)


class _StrategyLLM:
    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        assert "QUALIFIED" in user_prompt
        return json.dumps({"strategies": [{
            "strategy_type": "QUALIFIED_ALTERNATIVE",
            "title": "核验后采用已认证替代料",
            "summary": "候选料已有资格记录，仍需人工审批。",
            "rationale": "候选资格状态来自结构化影响结果。",
            "actions": ["确认切换时点与受影响产品"],
            "risks": ["需要进一步核对生产排程"],
        }]}, ensure_ascii=False)


class _ReviewLLM:
    def invoke_with_tools(
        self, *, messages: Sequence[BaseMessage], tools: Sequence[BaseTool]
    ) -> AIMessage:
        assert messages and tools
        return AIMessage(content=json.dumps({
            "decision": "PASS", "summary": "资格事实与策略一致",
            "issues": [], "recommendations": ["保留人工审批"],
        }, ensure_ascii=False))


def _run_ids(workflow_name: str) -> set[uuid.UUID]:
    with create_session() as session:
        return set(session.scalars(select(AgentRun.run_id).where(AgentRun.workflow_name == workflow_name)))


def _cleanup_runs(run_ids: set[uuid.UUID]) -> None:
    if not run_ids:
        return
    with create_session() as session:
        session.execute(delete(AuditEvent).where(AuditEvent.run_id.in_(run_ids)))
        session.execute(delete(ToolCall).where(ToolCall.run_id.in_(run_ids)))
        session.execute(delete(AgentStep).where(AgentStep.run_id.in_(run_ids)))
        session.execute(delete(AgentRun).where(AgentRun.run_id.in_(run_ids)))
        session.commit()


def _cleanup_case(state: MaterialSubstitutionWorkflowState) -> None:
    with create_session() as session:
        strategy_ids = list(session.scalars(select(ChangeStrategy.strategy_id).where(ChangeStrategy.ecr_id == state.ecr_id)))
        eco_ids = list(session.scalars(select(EngineeringChangeOrder.eco_id).where(EngineeringChangeOrder.ecr_id == state.ecr_id)))
        if eco_ids:
            session.execute(delete(ExecutionJob).where(ExecutionJob.eco_id.in_(eco_ids)))
            session.execute(delete(EngineeringChangeOrder).where(EngineeringChangeOrder.eco_id.in_(eco_ids)))
        if strategy_ids:
            session.execute(delete(ChangeStrategyAction).where(ChangeStrategyAction.strategy_id.in_(strategy_ids)))
            session.execute(delete(ChangeStrategy).where(ChangeStrategy.strategy_id.in_(strategy_ids)))
        if state.impact_id:
            session.execute(delete(ChangeImpact).where(ChangeImpact.impact_id == state.impact_id))
        if state.ecr_id:
            session.execute(delete(EngineeringChangeRequest).where(EngineeringChangeRequest.ecr_id == state.ecr_id))
        if state.case_id:
            session.execute(delete(ChangeCase).where(ChangeCase.case_id == state.case_id))
        session.commit()


def test_enterprise_tool_allowlist_covers_requested_read_paths():
    tools = {tool.name: tool for tool in get_enterprise_tools()}
    assert {"get_bom_structure", "find_where_used", "get_alternatives", "get_inventory",
            "get_suppliers", "get_supplier_parts", "get_purchase_order_records",
            "get_production_order_records", "get_sales_order_records"} <= tools.keys()
    assert "BRG-6204-A" in tools["get_bom_structure"].invoke({
        "part_number": "ROB-P100", "revision_code": "A", "as_of_date": "2026-09-20",
    })
    assert "ROB-P100" in tools["find_where_used"].invoke({
        "part_number": "BRG-6204-A", "revision_code": "A", "as_of_date": "2026-09-20",
    })
    assert "BRG-6204-B" in tools["get_alternatives"].invoke({"part_number": "BRG-6204-A", "revision_code": "A"})
    assert "BRG-6204-A" in tools["get_inventory"].invoke({"part_number": "BRG-6204-A", "revision_code": "A"})
    assert "SUP-001" in tools["get_suppliers"].invoke({"search": "SUP-001"})
    assert "BRG-6204-A" in tools["get_supplier_parts"].invoke({"part_number": "BRG-6204-A"})
    assert "PO-" in tools["get_purchase_order_records"].invoke({"open_only": True})
    assert "MO-" in tools["get_production_order_records"].invoke({})
    assert "SO-" in tools["get_sales_order_records"].invoke({})


def test_conversations_persist_isolate_and_resolve_context():
    before = _run_ids("enterprise_assistant")
    trace = TraceService()
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        llm_client=_AssistantLLM(), trace_service=trace,
    ))
    app = create_app()
    app.dependency_overrides[get_assistant_service] = lambda: service
    client = TestClient(app)
    ids: list[uuid.UUID] = []
    try:
        first = client.post("/api/v1/assistant/conversations", json={"title": "产品查询"})
        second = client.post("/api/v1/assistant/conversations", json={"title": "库存查询"})
        assert first.status_code == second.status_code == 201
        ids = [uuid.UUID(first.json()["id"]), uuid.UUID(second.json()["id"])]
        first_url = f"/api/v1/assistant/conversations/{ids[0]}"
        second_url = f"/api/v1/assistant/conversations/{ids[1]}"
        for url, question in (
            (first_url, "ROB-P100 有哪些零件？"),
            (first_url, "其中 BRG-6204-A 需要多少？"),
            (second_url, "BRG-6204-A 库存多少？"),
            (second_url, "它有哪些替代料？"),
        ):
            response = client.post(url + "/messages", json={"content": question})
            assert response.status_code == 200, response.text
            assert response.json()["assistant_message"]["content"]
        # A new service object reads persisted messages and context, not process memory.
        reopened = AssistantService().get(ids[0])
        other = AssistantService().get(ids[1])
        assert len(reopened.messages) == len(other.messages) == 4
        assert reopened.context.current_product == "ROB-P100"
        assert reopened.context.current_part == "BRG-6204-A"
        assert other.context.current_product is None
        assert other.context.current_part == "BRG-6204-A"
        assert "ROB-P100" in [message for message in reopened.messages if message.role == "assistant"][-1].content
        assert "BRG-6204-B" in [message for message in other.messages if message.role == "assistant"][-1].content
        assert client.get("/api/v1/assistant/conversations").status_code == 200
        with create_session() as session:
            runs = list(session.scalars(select(AgentRun).where(AgentRun.workflow_name == "enterprise_assistant")))
            assert any(run.status == "SUCCEEDED" for run in runs)
            calls = list(session.scalars(select(ToolCall).where(ToolCall.run_id.in_([run.run_id for run in runs]))))
            assert calls and all(call.tool_mode == "READ" and call.latency_ms is not None for call in calls)
    finally:
        with create_session() as session:
            for conversation_id in ids:
                session.execute(delete(AssistantConversation).where(AssistantConversation.id == conversation_id))
            session.commit()
        _cleanup_runs(_run_ids("enterprise_assistant") - before)


def test_assistant_resolves_ids_versions_dates_and_open_purchase():
    before = _run_ids("enterprise_assistant")
    service = AssistantService()
    conversation_id = service.create().id
    try:
        bom = service.send(conversation_id, "ROB-P100 需要哪些零件？")
        assert "BRG-6204-A" in bom.assistant_message.content
        assert "请提供" not in bom.assistant_message.content
        assert bom.context.current_revision == "A"

        inventory = service.send(conversation_id, "BRG-6204-A 当前库存是多少？")
        assert "现有量" in inventory.assistant_message.content
        alternatives = service.send(conversation_id, "它有哪些替代料？")
        assert "BRG-6204-B" in alternatives.assistant_message.content
        assert alternatives.workflow_suggestion is None
        where_used = service.send(conversation_id, "BRG-6204-A 被哪些产品使用？")
        assert "ROB-P100" in where_used.assistant_message.content
        purchase = service.send(conversation_id, "BRG-6204-A 有哪些未完成采购订单？")
        assert "PO-" in purchase.assistant_message.content
        assert "请提供" not in purchase.assistant_message.content

        run_ids = _run_ids("enterprise_assistant") - before
        with create_session() as session:
            calls = list(session.scalars(select(ToolCall).where(ToolCall.run_id.in_(run_ids))))
        bom_call = next(call for call in calls if call.tool_name == "get_bom_structure")
        assert "as_of_date" not in bom_call.arguments
        assert bom_call.arguments["part_number"] == "ROB-P100"
        assert bom_call.arguments["revision_code"] == "A"
        assert any(call.tool_name == "get_alternatives" for call in calls)
        assert any(call.tool_name == "get_purchase_orders" and call.arguments["open_only"] for call in calls)
    finally:
        with create_session() as session:
            session.execute(delete(AssistantConversation).where(AssistantConversation.id == conversation_id))
            session.commit()
        _cleanup_runs(_run_ids("enterprise_assistant") - before)


def test_failed_alternatives_tool_has_no_workflow_suggestion():
    def broken_alternatives(**_kwargs: object) -> str:
        raise RuntimeError("simulated unavailable data source")

    before = _run_ids("enterprise_assistant")
    trace = TraceService()
    tools = [tool for tool in get_enterprise_tools() if tool.name != "get_alternatives"]
    tools.append(StructuredTool.from_function(
        func=broken_alternatives, name="get_alternatives",
        description="Test unavailable alternatives", args_schema=GetAlternativesInput,
    ))
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        tools=tools, trace_service=trace,
    ))
    conversation_id = service.create().id
    try:
        result = service.send(conversation_id, "用 BRG-6204-B 替代 BRG-6204-A，评估一下")
        assert "查询失败" in result.assistant_message.content
        assert result.workflow_suggestion is None
    finally:
        with create_session() as session:
            session.execute(delete(AssistantConversation).where(AssistantConversation.id == conversation_id))
            session.commit()
        _cleanup_runs(_run_ids("enterprise_assistant") - before)


def test_model_supplied_identity_and_date_cannot_override_user_query():
    class MisleadingLLM:
        def invoke_with_tools(
            self, *, messages: Sequence[BaseMessage], tools: Sequence[BaseTool]
        ) -> AIMessage:
            if any(isinstance(message, ToolMessage) for message in messages):
                return AIMessage(content="已核对库存事实。")
            return AIMessage(content="", tool_calls=[{
                "name": "get_inventory",
                "args": {
                    "part_number": "MOTOR-FAKE", "revision_code": "Z",
                    "as_of_date": "2025-01-01",
                },
                "id": uuid.uuid4().hex, "type": "tool_call",
            }])

    before = _run_ids("enterprise_assistant")
    trace = TraceService()
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        llm_client=MisleadingLLM(), trace_service=trace,
    ))
    conversation_id = service.create().id
    try:
        result = service.send(conversation_id, "请分析 BRG-6204-A 的业务情况")
        assert result.context.current_part == "BRG-6204-A"
        assert "现有量" in result.assistant_message.content
        assert "已核对库存事实。" not in result.assistant_message.content
        run_ids = _run_ids("enterprise_assistant") - before
        with create_session() as session:
            call = session.scalar(select(ToolCall).where(
                ToolCall.run_id.in_(run_ids), ToolCall.tool_name == "get_inventory",
            ))
        assert call is not None
        assert call.arguments == {"part_number": "BRG-6204-A", "revision_code": "A"}
    finally:
        with create_session() as session:
            session.execute(delete(AssistantConversation).where(AssistantConversation.id == conversation_id))
            session.commit()
        _cleanup_runs(_run_ids("enterprise_assistant") - before)


def test_workflow_suggestions_require_scenario_and_successful_facts():
    before = _run_ids("enterprise_assistant")
    service = AssistantService()
    conversation_id = service.create().id
    try:
        lookup = service.send(conversation_id, "BRG-6204-A 有哪些替代料？")
        assert lookup.workflow_suggestion is None
        evaluation = service.send(
            conversation_id, "用 BRG-6204-B 替代 BRG-6204-A，评估一下",
        )
        assert evaluation.workflow_suggestion is not None
        assert evaluation.workflow_suggestion.workflow == "material_substitution"
        assert evaluation.workflow_suggestion.prefill["candidate_part_number"] == "BRG-6204-B"
        eol = service.send(conversation_id, "BRG-6204-A 停产，需要分析吗？")
        assert eol.workflow_suggestion is not None
        assert eol.workflow_suggestion.workflow == "supplier_eol"
    finally:
        with create_session() as session:
            session.execute(delete(AssistantConversation).where(AssistantConversation.id == conversation_id))
            session.commit()
        _cleanup_runs(_run_ids("enterprise_assistant") - before)


def test_v23_followups_and_supplier_conversation_are_isolated():
    before = _run_ids("enterprise_assistant")
    service = AssistantService()
    first = service.create().id
    second = service.create().id
    try:
        questions = [
            "ROB-P100 需要哪些零件？",
            "其中 BRG-6204-A 需要多少？",
            "这个零件当前库存多少？",
            "它有哪些替代料？",
            "哪个是已认证的？",
        ]
        turns = [service.send(first, question) for question in questions]
        assert "BRG-6204-A" in turns[1].assistant_message.content
        assert "现有量" in turns[2].assistant_message.content
        assert "BRG-6204-B" in turns[3].assistant_message.content
        assert "BRG-6204-B" in turns[4].assistant_message.content
        assert "BRG-6204-C" not in turns[4].assistant_message.content
        assert all(turn.answer_status == "SUCCESS" for turn in turns)
        product_followup = service.send(first, "这个产品有哪些零件？")
        assert "ROB-P100" in product_followup.assistant_message.content
        assert product_followup.context.current_product == "ROB-P100"

        supplier = service.send(second, "SUP-001 供应哪些零件？")
        orders = service.send(second, "这个供应商有哪些未完成采购订单？")
        assert supplier.context.current_supplier_code == "SUP-001"
        assert orders.answer_status == "SUCCESS"
        assert "SUP-001" in orders.assistant_message.content
        assert service.get(first).context.current_supplier_code is None
        assert service.get(second).context.current_product is None
        run_ids = _run_ids("enterprise_assistant") - before
        with create_session() as session:
            calls = list(session.scalars(select(ToolCall).where(ToolCall.run_id.in_(run_ids))))
        supplier_orders = [call for call in calls if call.tool_name == "get_purchase_order_records"]
        assert supplier_orders and supplier_orders[-1].arguments["supplier_code"] == "SUP-001"
        assert supplier_orders[-1].arguments["open_only"] is True
        assert all("2025-01-01" not in str(call.arguments) for call in calls)
        assert shanghai_datetime(turns[0].assistant_message.created_at).utcoffset().total_seconds() == 8 * 3600
    finally:
        with create_session() as session:
            for conversation_id in (first, second):
                session.execute(delete(AssistantConversation).where(AssistantConversation.id == conversation_id))
            session.commit()
        _cleanup_runs(_run_ids("enterprise_assistant") - before)


def test_v23_no_data_missing_input_and_tool_failure_are_distinct():
    def empty_alternatives(**kwargs: object) -> str:
        return json.dumps({"part_number": kwargs["part_number"], "rows": []})

    before = _run_ids("enterprise_assistant")
    trace = TraceService()
    tools = [tool for tool in get_enterprise_tools() if tool.name != "get_alternatives"]
    tools.append(StructuredTool.from_function(
        func=empty_alternatives, name="get_alternatives",
        description="Test empty alternatives", args_schema=GetAlternativesInput,
    ))
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        tools=tools, trace_service=trace,
    ))
    conversation_id = service.create().id
    try:
        missing = service.send(conversation_id, "库存多少？")
        empty = service.send(conversation_id, "BRG-6204-A 有哪些替代料？")
        assert missing.answer_status == "MISSING_INPUT"
        assert empty.answer_status == "NO_DATA"
        assert "暂无" in empty.assistant_message.content
        assert empty.workflow_suggestion is None
        assert missing.assistant_message.content != empty.assistant_message.content
    finally:
        with create_session() as session:
            session.execute(delete(AssistantConversation).where(AssistantConversation.id == conversation_id))
            session.commit()
        _cleanup_runs(_run_ids("enterprise_assistant") - before)


def test_v23_llm_failure_is_safe_and_next_turn_can_retry():
    class FlakyLLM:
        failed = False

        def invoke_with_tools(
            self, *, messages: Sequence[BaseMessage], tools: Sequence[BaseTool]
        ) -> AIMessage:
            if not self.failed:
                self.failed = True
                raise LLMResponseError("private provider details")
            if any(isinstance(message, ToolMessage) for message in messages):
                return AIMessage(content="invented detail")
            return AIMessage(content="", tool_calls=[{
                "name": "get_inventory", "args": {},
                "id": uuid.uuid4().hex, "type": "tool_call",
            }])

    before = _run_ids("enterprise_assistant")
    trace = TraceService()
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        llm_client=FlakyLLM(), trace_service=trace,
    ))
    app = create_app()
    app.dependency_overrides[get_assistant_service] = lambda: service
    client = TestClient(app)
    conversation_id = uuid.UUID(client.post(
        "/api/v1/assistant/conversations", json={"title": "重试测试"},
    ).json()["id"])
    path = f"/api/v1/assistant/conversations/{conversation_id}/messages"
    try:
        failed = client.post(path, json={"content": "请分析 BRG-6204-A 的业务情况"})
        assert failed.status_code == 503
        assert "private provider details" not in failed.text
        retried = client.post(path, json={"content": "请分析 BRG-6204-A 的业务情况"})
        assert retried.status_code == 200
        assert "现有量" in retried.json()["assistant_message"]["content"]
        assert "invented detail" not in retried.text
    finally:
        with create_session() as session:
            session.execute(delete(AssistantConversation).where(AssistantConversation.id == conversation_id))
            session.commit()
        _cleanup_runs(_run_ids("enterprise_assistant") - before)


def test_v23_chinese_fact_formatting_and_review_json_prefix():
    inventory = ToolFact(
        name="get_inventory", arguments={"part_number": "BRG-6204-A"},
        data={"rows": [{"qty_on_hand": "700.0000", "qty_reserved": "6.0000"}]},
    )
    alternatives = ToolFact(
        name="get_alternatives", arguments={"part_number": "BRG-6204-A"},
        data={"rows": [{"alternative_part_number": "BRG-6204-B",
                        "alternative_revision_code": "A", "qualification_status": "QUALIFIED"}]},
    )
    text = EnterpriseAssistant._format_fact(inventory)
    table = EnterpriseAssistant._format_fact(alternatives)
    assert "700.0000" not in text and "现有量 700" in text
    assert "| 替代零件号 |" in table and "已认证" in table
    assert "QUALIFIED" not in table and "{" not in table
    parsed = ReviewAgent._parse_review(
        'Checked facts. {"decision":"PASS","summary":"通过","issues":[],"recommendations":[]}',
    )
    assert parsed.decision == "PASS"


def test_v23_timestamp_columns_are_timezone_aware():
    for model, fields in (
        (AgentRun, ("started_at", "finished_at")),
        (AgentStep, ("started_at", "finished_at")),
        (ToolCall, ("created_at",)),
        (AuditEvent, ("created_at",)),
        (AssistantConversation, ("created_at", "updated_at")),
        (AssistantMessage, ("created_at",)),
        (ChangeCase, ("created_at", "updated_at")),
        (EngineeringChangeOrder, ("created_at", "updated_at")),
        (ExecutionJob, ("created_at", "updated_at", "completed_at")),
    ):
        for field in fields:
            assert model.__table__.columns[field].type.timezone is True


@pytest.mark.skipif(os.getenv("CHANGEPILOT_REAL_SMOKE") != "1", reason="explicit real-model smoke only")
def test_real_deepseek_material_substitution_approve_smoke():
    before = _run_ids("material_substitution")
    fake_review = os.getenv("CHANGEPILOT_SMOKE_FAKE_REVIEW") == "1"
    runtime = MaterialSubstitutionRuntime(
        checkpointer=InMemorySaver() if not os.getenv("CHANGEPILOT_REAL_SMOKE") else None,
        review_agent_factory=(lambda: ReviewAgent(_ReviewLLM())) if fake_review else None,
    )
    client = TestClient(create_app(material_runtime=runtime))
    thread_id = "sub-real-" + uuid.uuid4().hex[:12]
    try:
        started = client.post("/api/v1/workflows/material-substitution", json={
            "thread_id": thread_id, "part_number": "BRG-6204-A", "revision_code": "A",
            "candidate_part_number": "BRG-6204-B",
            "as_of_date": current_business_date().isoformat(),
            "requested_by": "v23.smoke",
        })
        assert started.status_code == 200, started.text
        state = started.json()["state"]
        assert state["impact"] and state["strategies"] and state["review_result"]
        assert started.json()["status"] == "INTERRUPTED", {
            "review": state["review_result"], "strategies": state["strategies"],
        }
        assert state["review_result"]["decision"] == "PASS"
        completed = client.post(
            f"/api/v1/workflows/material-substitution/{thread_id}/approval",
            json={"decision": "APPROVE", "comment": "V2.3 真实模型 smoke test",
                  "reviewer": "v23.smoke", "selected_strategy_index": 0},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"
        assert completed.json()["state"]["execution_result"]["eco_id"]
    finally:
        _cleanup_runs(_run_ids("material_substitution") - before)
        with create_session() as session:
            case_id = session.scalar(select(ChangeCase.case_id).where(
                ChangeCase.idempotency_key == f"material-substitution:{thread_id}",
            ))
            ecr_id = session.scalar(select(EngineeringChangeRequest.ecr_id).where(
                EngineeringChangeRequest.case_id == case_id,
            )) if case_id else None
            impact_id = session.scalar(select(ChangeImpact.impact_id).where(
                ChangeImpact.ecr_id == ecr_id,
            )) if ecr_id else None
        if case_id:
            _cleanup_case(SimpleNamespace(case_id=case_id, ecr_id=ecr_id, impact_id=impact_id))


@pytest.mark.parametrize("decision", ["APPROVE", "REJECT"])
def test_material_substitution_workflow(decision: str):
    before = _run_ids("material_substitution")
    runtime = MaterialSubstitutionRuntime(
        checkpointer=InMemorySaver(),
        strategy_agent_factory=lambda: StrategyAgent(_StrategyLLM()),
        review_agent_factory=lambda: ReviewAgent(_ReviewLLM()),
    )
    client = TestClient(create_app(material_runtime=runtime))
    thread_id = "sub-test-" + uuid.uuid4().hex[:12]
    state = None
    try:
        started = client.post("/api/v1/workflows/material-substitution", json={
            "thread_id": thread_id, "part_number": "BRG-6204-A", "revision_code": "A",
            "candidate_part_number": "BRG-6204-B", "as_of_date": "2026-09-20",
        })
        assert started.status_code == 200, started.text
        state = MaterialSubstitutionWorkflowState.model_validate(started.json()["state"])
        assert started.json()["status"] == "INTERRUPTED"
        assert state.impact and state.impact.qualification_status == "QUALIFIED"
        assert state.impact.candidate_revision_code == "A"
        assert state.case_id and state.ecr_id and state.impact_id
        assert client.get(f"/api/v1/workflows/material-substitution/{thread_id}").status_code == 200
        completed = client.post(
            f"/api/v1/workflows/material-substitution/{thread_id}/approval",
            json={"decision": decision, "comment": "test", "reviewer": "test.manager"},
        )
        assert completed.status_code == 200, completed.text
        state = MaterialSubstitutionWorkflowState.model_validate(completed.json()["state"])
        assert completed.json()["status"] == "COMPLETED"
        assert state.approval and state.approval.decision == decision
        assert bool(state.execution_result) == (decision == "APPROVE")
        with create_session() as session:
            assert session.scalar(select(ChangeCase.case_type).where(ChangeCase.case_id == state.case_id)) == "MATERIAL_SUBSTITUTION"
            assert session.scalar(select(ChangeImpact.evidence).where(ChangeImpact.impact_id == state.impact_id))["qualification_status"] == "QUALIFIED"
            assert (session.scalar(select(EngineeringChangeOrder.eco_id).where(EngineeringChangeOrder.ecr_id == state.ecr_id)) is not None) == (decision == "APPROVE")
    finally:
        if state is not None:
            _cleanup_runs(_run_ids("material_substitution") - before)
            _cleanup_case(state)


def test_unqualified_candidate_cannot_pass_as_qualified():
    before = _run_ids("material_substitution")
    runtime = MaterialSubstitutionRuntime(
        checkpointer=InMemorySaver(),
        strategy_agent_factory=lambda: StrategyAgent(_StrategyLLM()),
        review_agent_factory=lambda: ReviewAgent(_ReviewLLM()),
    )
    client = TestClient(create_app(material_runtime=runtime))
    state = None
    try:
        response = client.post("/api/v1/workflows/material-substitution", json={
            "thread_id": "sub-unsafe-" + uuid.uuid4().hex[:12],
            "part_number": "BRG-6204-A", "revision_code": "A",
            "candidate_part_number": "BRG-6204-C", "as_of_date": "2026-09-20",
        })
        assert response.status_code == 200, response.text
        state = MaterialSubstitutionWorkflowState.model_validate(response.json()["state"])
        assert state.impact and state.impact.qualification_status == "UNQUALIFIED"
        assert state.review_result and state.review_result.decision == "REVISE"
        assert state.revision_count == 2
        assert response.json()["status"] == "COMPLETED"
        assert state.approval is None and state.execution_result is None
    finally:
        if state is not None:
            _cleanup_runs(_run_ids("material_substitution") - before)
            _cleanup_case(state)
