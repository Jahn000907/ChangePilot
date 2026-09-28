"""Focused Supervisor and domain-specialist integration checks."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool, StructuredTool
from sqlalchemy import delete, select

from app.agents.enterprise_assistant import EnterpriseAssistant
from app.db.postgres.models.agent import AgentRun, AgentStep, ToolCall
from app.db.postgres.models.assistant import AssistantConversation
from app.db.postgres.models.audit import AuditEvent
from app.db.postgres.session import create_session
from app.llm.client import DeepSeekLLMClient
from app.main import create_app
from app.services.assistant import AssistantService
from app.services.trace import TraceService
from app.tools.langchain import get_enterprise_tools
from app.tools.schemas import GetInventoryInput


class _SupervisorLLM:
    def __init__(self, *, unsafe_tool: bool = False, fabricated_summary: bool = False) -> None:
        self.plans: list[list[str]] = []
        self.unsafe_tool = unsafe_tool
        self.fabricated_summary = fabricated_summary

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        if "跨域/综合" not in system_prompt:
            if self.fabricated_summary:
                return json.dumps({
                    "judgment": "PO-FAKE-999 已确认延期 99999 天。",
                    "recommendations": ["立即按该虚构订单处置。"],
                }, ensure_ascii=False)
            return json.dumps({
                "judgment": "已核验领域事实提示应审慎评估，未核验事项不能视为已确认。",
                "recommendations": ["核对缺口后再考虑正式流程。"],
            }, ensure_ascii=False)
        question = json.loads(user_prompt)["question"]
        if self.unsafe_tool:
            assignments = [("SupplyAgent", ["get_bom_structure"])]
        elif "综合分析" in question:
            assignments = [
                ("StructureAgent", ["find_where_used", "get_alternatives"]),
                ("SupplyAgent", ["get_supplier_parts", "get_inventory", "get_purchase_orders"]),
                ("ProductionAgent", ["get_production_requirements"]),
                ("DeliveryAgent", ["get_sales_order_records"]),
            ]
        elif "供应风险" in question:
            assignments = [
                ("SupplyAgent", ["get_inventory", "get_purchase_orders"]),
                ("StructureAgent", ["find_where_used"]),
            ]
        else:
            assignments = [
                ("StructureAgent", ["get_bom_structure", "find_where_used"]),
                ("SupplyAgent", ["get_inventory"]),
                ("ProductionAgent", ["get_production_requirements"]),
            ]
        self.plans.append([name for name, _ in assignments])
        return json.dumps({"multi_agent": True, "agents": [
            {"agent_name": name, "task": f"核对{name}领域事实", "tools": tools}
            for name, tools in assignments
        ]}, ensure_ascii=False)

    def invoke_with_tools(
        self, *, messages: Sequence[BaseMessage], tools: Sequence[BaseTool]
    ) -> AIMessage:
        return AIMessage(content="通用解释。")


def _run_ids() -> set[uuid.UUID]:
    with create_session() as session:
        return set(session.scalars(select(AgentRun.run_id).where(
            AgentRun.workflow_name == "enterprise_assistant",
        )))


def _cleanup(conversations: list[uuid.UUID], before: set[uuid.UUID]) -> None:
    with create_session() as session:
        for conversation in conversations:
            session.execute(delete(AssistantConversation).where(AssistantConversation.id == conversation))
        session.commit()
    run_ids = _run_ids() - before
    if not run_ids:
        return
    with create_session() as session:
        session.execute(delete(AuditEvent).where(AuditEvent.run_id.in_(run_ids)))
        session.execute(delete(ToolCall).where(ToolCall.run_id.in_(run_ids)))
        session.execute(delete(AgentStep).where(AgentStep.run_id.in_(run_ids)))
        session.execute(delete(AgentRun).where(AgentRun.run_id.in_(run_ids)))
        session.commit()


def _service(llm: _SupervisorLLM, tools: list[BaseTool] | None = None) -> AssistantService:
    trace = TraceService()
    return AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        llm_client=llm, tools=tools, trace_service=trace,
    ))


def test_supervisor_dynamically_selects_domains_and_traces_tools() -> None:
    before = _run_ids()
    llm = _SupervisorLLM()
    service = _service(llm)
    conversation = service.create().id
    try:
        cases = (
            ("综合分析 BRG-6204-A 停产会对公司造成哪些影响？", 4),
            ("BRG-6204-A 的供应风险怎么样？", 2),
            ("ROB-P100 如果 BRG-6204-A 无法供应，会影响什么？", 3),
        )
        for question, count in cases:
            result = service.send(conversation, question)
            assert result.answer_status in {"SUCCESS", "TOOL_ERROR"}
            assert len(llm.plans[-1]) == count
            assert "### 企业事实" in result.assistant_message.content
            assert "### 综合判断" in result.assistant_message.content
        assert llm.plans[1] == ["SupplyAgent", "StructureAgent"]
        with create_session() as session:
            runs = _run_ids() - before
            steps = list(session.scalars(select(AgentStep).where(AgentStep.run_id.in_(runs))))
            calls = list(session.scalars(select(ToolCall).where(ToolCall.run_id.in_(runs))))
        names = {step.node_name for step in steps}
        assert {"supervisor_plan", "supervisor_summary", "StructureAgent",
                "SupplyAgent", "ProductionAgent", "DeliveryAgent"} <= names
        assert calls and any(call.agent_name == "SupplyAgent" for call in calls)
        assert all(call.agent_name in {"StructureAgent", "SupplyAgent",
                                       "ProductionAgent", "DeliveryAgent"} for call in calls)
        run_id = next(run_id for run_id in runs if any(
            step.run_id == run_id and step.node_name == "DeliveryAgent" for step in steps
        ))
        detail = TestClient(create_app()).get(f"/api/v1/agent-runs/{run_id}")
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert payload["has_supervisor"] is True
        assert len(payload["selected_agents"]) == 4
        assert any(step["node_name"] == "SupplyAgent" and step["tool_calls"]
                   for step in payload["steps"])
        partial_id = next(run_id for run_id in runs if any(
            step.run_id == run_id and step.node_name == "SupplyAgent" for step in steps
        ) and not any(step.run_id == run_id and step.node_name == "DeliveryAgent" for step in steps))
        partial = TestClient(create_app()).get(f"/api/v1/agent-runs/{partial_id}").json()
        assert "DeliveryAgent" not in partial["selected_agents"]
        assert not any(step["node_name"] == "DeliveryAgent" for step in partial["steps"])
    finally:
        _cleanup([conversation], before)


def test_simple_question_bypasses_supervisor() -> None:
    before = _run_ids()
    llm = _SupervisorLLM()
    service = _service(llm)
    conversation = service.create().id
    try:
        inventory = service.send(conversation, "BRG-6204-A 当前库存多少？")
        assert inventory.answer_status == "SUCCESS"
        assert inventory.assistant_message.metadata_json["tool_names"] == ["get_inventory"]
        concept = service.send(conversation, "什么是 BOM？")
        assert concept.answer_status == "SUCCESS"
        assert concept.assistant_message.metadata_json["tool_names"] == []
        assert llm.plans == []
        with create_session() as session:
            runs = _run_ids() - before
            names = set(session.scalars(select(AgentStep.node_name).where(
                AgentStep.run_id.in_(runs),
            )))
        assert "supervisor_plan" not in names
    finally:
        _cleanup([conversation], before)


def test_domain_allowlist_blocks_supervisor_tool_escalation() -> None:
    before = _run_ids()
    service = _service(_SupervisorLLM(unsafe_tool=True))
    conversation = service.create().id
    try:
        result = service.send(conversation, "BRG-6204-A 的供应风险怎么样？")
        assert result.answer_status == "TOOL_ERROR"
        assert "暂无经核验的企业事实" in result.assistant_message.content
        assert result.workflow_suggestion is None
        with create_session() as session:
            runs = _run_ids() - before
            calls = list(session.scalars(select(ToolCall).where(ToolCall.run_id.in_(runs))))
        assert not calls
    finally:
        _cleanup([conversation], before)


def test_one_domain_tool_failure_keeps_partial_facts_and_unknowns() -> None:
    before = _run_ids()

    def fail_inventory(**kwargs: object) -> str:
        raise RuntimeError("synthetic failure")

    tools = [tool for tool in get_enterprise_tools() if tool.name != "get_inventory"]
    tools.append(StructuredTool.from_function(
        func=fail_inventory, name="get_inventory", description="test failure",
        args_schema=GetInventoryInput,
    ))
    service = _service(_SupervisorLLM(), tools)
    conversation = service.create().id
    try:
        result = service.send(conversation, "BRG-6204-A 的供应风险怎么样？")
        assert result.answer_status == "TOOL_ERROR"
        text = result.assistant_message.content
        assert "### 不确定项" in text and "get_inventory 查询失败" in text
        assert "### 企业事实" in text
        assert result.workflow_suggestion is None
        with create_session() as session:
            runs = _run_ids() - before
            calls = list(session.scalars(select(ToolCall).where(ToolCall.run_id.in_(runs))))
        assert any(call.tool_name == "get_inventory" and call.status == "FAILED" for call in calls)
        assert any(call.status == "SUCCEEDED" for call in calls)
    finally:
        _cleanup([conversation], before)


def test_supervisor_rejects_fabricated_identifier_and_number() -> None:
    before = _run_ids()
    service = _service(_SupervisorLLM(fabricated_summary=True))
    conversation = service.create().id
    try:
        result = service.send(conversation, "BRG-6204-A 的供应风险怎么样？")
        assert "PO-FAKE-999" not in result.assistant_message.content
        assert "99999" not in result.assistant_message.content
        assert "未核验事项" in result.assistant_message.content
    finally:
        _cleanup([conversation], before)


@pytest.mark.skipif(
    os.getenv("CHANGEPILOT_REAL_MULTI_AGENT_SMOKE") != "1",
    reason="explicit real DeepSeek smoke only",
)
def test_real_deepseek_supervisor_selects_domains() -> None:
    before = _run_ids()
    trace = TraceService()
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        llm_client=DeepSeekLLMClient(), trace_service=trace,
    ))
    conversation = service.create().id
    try:
        result = service.send(conversation, "BRG-6204-A 的供应风险怎么样？")
        assert result.answer_status in {"SUCCESS", "TOOL_ERROR"}
        assert "### 企业事实" in result.assistant_message.content
        with create_session() as session:
            runs = _run_ids() - before
            names = set(session.scalars(select(AgentStep.node_name).where(
                AgentStep.run_id.in_(runs),
            )))
        assert "supervisor_plan" in names
        assert "SupplyAgent" in names
        assert "DeliveryAgent" not in names
    finally:
        _cleanup([conversation], before)
