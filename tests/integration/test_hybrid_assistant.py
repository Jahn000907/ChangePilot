"""Hybrid assistant: general answers, grounded facts and multi-tool analysis."""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from sqlalchemy import delete, select

from app.agents.enterprise_assistant import EnterpriseAssistant, ToolFact
from app.db.postgres.models.agent import AgentRun, AgentStep, ToolCall
from app.db.postgres.models.assistant import AssistantConversation
from app.db.postgres.models.audit import AuditEvent
from app.db.postgres.session import create_session
from app.llm.client import DeepSeekLLMClient
from app.services.assistant import AssistantService
from app.services.trace import TraceService
from app.tools.langchain import get_enterprise_tools
from app.tools.schemas import GetAlternativesInput, GetInventoryInput


class _HybridLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def invoke_with_tools(
        self, *, messages: Sequence[BaseMessage], tools: Sequence[BaseTool]
    ) -> AIMessage:
        question = next(str(message.content) for message in reversed(messages)
                        if isinstance(message, HumanMessage)
                        and not str(message.content).startswith("当前会话上下文"))
        returned = [message.name for message in messages if isinstance(message, ToolMessage)]
        self.calls.append((question, returned))
        if returned:
            return AIMessage(content="已查得事实支持进一步核对交期与生产安排；这是分析判断，不是新的企业记录。")
        calls: list[str] = []
        if "结合" in question and "库存" in question and "采购" in question:
            calls = ["get_inventory", "get_purchase_orders"]
        elif "替代料情况" in question:
            calls = ["get_alternatives"]
        elif "BOM" in question and "Where-Used" in question:
            calls = ["get_bom_structure", "find_where_used"]
        if calls:
            return AIMessage(content="", tool_calls=[{
                "name": name, "args": {}, "id": uuid.uuid4().hex, "type": "tool_call",
            } for name in calls])
        return AIMessage(content="这是通用解释或改写，不包含当前企业记录。")


def _runs_before() -> set[uuid.UUID]:
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
    with create_session() as session:
        run_ids = _runs_before() - before
        if run_ids:
            session.execute(delete(AuditEvent).where(AuditEvent.run_id.in_(run_ids)))
            session.execute(delete(ToolCall).where(ToolCall.run_id.in_(run_ids)))
            session.execute(delete(AgentStep).where(AgentStep.run_id.in_(run_ids)))
            session.execute(delete(AgentRun).where(AgentRun.run_id.in_(run_ids)))
        session.commit()


def _service(llm: _HybridLLM, tools: list[BaseTool] | None = None) -> AssistantService:
    trace = TraceService()
    return AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        llm_client=llm, tools=tools, trace_service=trace,
    ))


def test_every_enterprise_tool_description_distinguishes_fact_and_concept() -> None:
    tools = get_enterprise_tools()
    assert tools
    assert all("查询" in tool.description and "无需调用" in tool.description for tool in tools)


@pytest.mark.parametrize("question", [
    "什么是 BOM？", "ECO 和 ECR 有什么区别？",
    "帮我解释一下供应商停产通常有哪些风险。",
    "帮我把‘请尽快确认交付时间’改写得更正式一些。",
])
def test_general_questions_need_no_tool(question: str) -> None:
    before = _runs_before()
    llm = _HybridLLM()
    service = _service(llm)
    conversation = service.create().id
    try:
        answer = service.send(conversation, question)
        assert answer.answer_status == "SUCCESS"
        assert "通用解释" in answer.assistant_message.content
        assert answer.assistant_message.metadata_json["tool_names"] == []
        assert llm.calls and llm.calls[-1][1] == []
        assert answer.workflow_suggestion is None
    finally:
        _cleanup([conversation], before)


def test_general_then_company_bom_and_session_isolation() -> None:
    before = _runs_before()
    service = _service(_HybridLLM())
    first, second = service.create().id, service.create().id
    try:
        assert service.send(first, "什么是 BOM？").answer_status == "SUCCESS"
        result = service.send(first, "那 ROB-P100 的 BOM 呢？")
        assert result.answer_status == "SUCCESS"
        assert "ROB-P100" in result.assistant_message.content
        assert "get_bom_structure" in result.assistant_message.metadata_json["tool_names"]
        assert service.get(first).context.current_product == "ROB-P100"
        assert service.get(second).context.current_product is None
        assert service.get(second).messages == []
    finally:
        _cleanup([first, second], before)


@pytest.mark.parametrize("question,expected", [
    ("ROB-P100 需要哪些零件？", "get_bom_structure"),
    ("BRG-6204-A 当前库存是多少？", "get_inventory"),
    ("BRG-6204-A 有哪些替代料？", "get_alternatives"),
    ("BRG-6204-A 被哪些产品使用？", "find_where_used"),
    ("BRG-6204-A 有哪些未完成采购订单？", "get_purchase_orders"),
])
def test_company_facts_require_matching_tool(question: str, expected: str) -> None:
    before = _runs_before()
    service = _service(_HybridLLM())
    conversation = service.create().id
    try:
        result = service.send(conversation, question)
        assert result.answer_status == "SUCCESS"
        assert expected in result.assistant_message.metadata_json["tool_names"]
        assert "通用解释" not in result.assistant_message.content
    finally:
        _cleanup([conversation], before)


@pytest.mark.parametrize("question,expected", [
    ("结合 BRG-6204-A 的库存和采购情况，分析一下供应风险。",
     {"get_inventory", "get_purchase_orders"}),
    ("根据 BRG-6204-A 的替代料情况，解释哪种替代路径风险更低。",
     {"get_alternatives"}),
    ("结合 ROB-P100 的 BOM 和 BRG-6204-A 的 Where-Used，说明这个零件为什么重要。",
     {"get_bom_structure", "find_where_used"}),
])
def test_mixed_questions_use_tools_before_analysis(question: str, expected: set[str]) -> None:
    before = _runs_before()
    llm = _HybridLLM()
    service = _service(llm)
    conversation = service.create().id
    try:
        result = service.send(conversation, question)
        assert result.answer_status == "SUCCESS"
        assert expected <= set(result.assistant_message.metadata_json["tool_names"])
        assert "企业事实：" in result.assistant_message.content
        assert "分析判断：" in result.assistant_message.content
        assert expected <= set(llm.calls[-1][1])
        assert result.workflow_suggestion is None
    finally:
        _cleanup([conversation], before)


def test_tool_failure_does_not_turn_into_model_fact_or_suggestion() -> None:
    before = _runs_before()
    def failed_inventory(**kwargs: object) -> str:
        raise RuntimeError("synthetic query failure")

    tools = [tool for tool in get_enterprise_tools() if tool.name != "get_inventory"]
    tools.append(StructuredTool.from_function(
        func=failed_inventory, name="get_inventory", description="test failure",
        args_schema=GetInventoryInput,
    ))
    service = _service(_HybridLLM(), tools)
    conversation = service.create().id
    try:
        result = service.send(conversation,
                              "结合 BRG-6204-A 的库存和采购情况，分析一下供应风险。")
        assert result.answer_status == "TOOL_ERROR"
        assert "分析判断" not in result.assistant_message.content
        assert result.workflow_suggestion is None
    finally:
        _cleanup([conversation], before)


def test_empty_tool_result_stays_no_data_even_if_model_writes_analysis() -> None:
    before = _runs_before()

    def empty_alternatives(**kwargs: object) -> str:
        return '{"rows":[]}'

    tools = [tool for tool in get_enterprise_tools() if tool.name != "get_alternatives"]
    tools.append(StructuredTool.from_function(
        func=empty_alternatives, name="get_alternatives", description="test empty result",
        args_schema=GetAlternativesInput,
    ))
    service = _service(_HybridLLM(), tools)
    conversation = service.create().id
    try:
        result = service.send(conversation,
                              "根据 BRG-6204-A 的替代料情况，解释哪种替代路径风险更低。")
        assert result.answer_status == "NO_DATA"
        assert "分析判断" not in result.assistant_message.content
        assert result.workflow_suggestion is None
    finally:
        _cleanup([conversation], before)


def test_model_analysis_rejects_unverified_number_or_part() -> None:
    fact = ToolFact("get_inventory", {"part_number": "BRG-6204-A"}, {
        "rows": [{"qty_on_hand": "700.0000"}],
    })
    question = "分析 BRG-6204-A 的库存风险"
    assert EnterpriseAssistant._grounded_analysis("库存 700，需要核对需求。", [fact], question)
    assert not EnterpriseAssistant._grounded_analysis("库存 99999。", [fact], question)
    assert not EnterpriseAssistant._grounded_analysis("MOTOR-FAKE 可以替换。", [fact], question)


@pytest.mark.skipif(
    os.getenv("CHANGEPILOT_REAL_HYBRID_SMOKE") != "1",
    reason="explicit real DeepSeek smoke only",
)
def test_real_deepseek_selects_tools_for_mixed_query() -> None:
    before = _runs_before()
    trace = TraceService()
    service = AssistantService(trace_service=trace, assistant=EnterpriseAssistant(
        llm_client=DeepSeekLLMClient(), trace_service=trace,
    ))
    conversation = service.create().id
    try:
        general = service.send(conversation, "什么是 BOM？请用一句话说明。")
        assert general.answer_status == "SUCCESS"
        assert general.assistant_message.metadata_json["tool_names"] == []
        mixed = service.send(conversation,
                             "结合 BRG-6204-A 的库存和采购情况，分析一下供应风险。")
        assert mixed.answer_status == "SUCCESS", mixed.assistant_message.content
        assert {"get_inventory", "get_purchase_orders"} <= set(
            mixed.assistant_message.metadata_json["tool_names"]
        )
    finally:
        _cleanup([conversation], before)
