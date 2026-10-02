"""Bounded Supervisor plan recovery and safe fallback."""

from __future__ import annotations

import uuid

import pytest

from app.agents.enterprise_assistant import ToolFact
from app.agents.supervisor import SupervisorAgent, SupervisorPlanningError
from app.domain.dto.assistant import AssistantContext
from app.domain.dto.multi_agent import DomainAgentResult, DomainName


class _Trace:
    def __init__(self) -> None:
        self.finishes: list[dict[str, object]] = []

    def start_step(self, **kwargs: object) -> tuple[uuid.UUID, float]:
        return uuid.uuid4(), 0.0

    def finish_step(self, **kwargs: object) -> None:
        self.finishes.append(kwargs)


class _Model:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0
        self.prompts: list[str] = []

    def generate_json(self, **kwargs: object) -> str:
        self.calls += 1
        self.prompts.append(str(kwargs["system_prompt"]))
        return self.responses.pop(0)


VALID = '{"multi_agent":true,"agents":[{"agent_name":"SupplyAgent","task":"核验供应","tools":["get_inventory"]}]}'
INVALID = '{"multi_agent":true,"agents":[{"agent_name":"UnknownAgent","task":"x"}]}'


def _agent(responses: list[str]) -> tuple[SupervisorAgent, _Model, _Trace]:
    model = _Model(responses)
    trace = _Trace()
    return SupervisorAgent(model, object(), trace), model, trace


def test_valid_plan_needs_one_call() -> None:
    agent, model, trace = _agent([VALID])
    plan = agent._plan("结合库存和采购分析风险", AssistantContext(), uuid.uuid4())
    assert [item.agent_name.value for item in plan.agents] == ["SupplyAgent"]
    assert model.calls == 1
    assert trace.finishes[-1]["status"] == "SUCCEEDED"


def test_invalid_plan_retries_once() -> None:
    agent, model, trace = _agent([INVALID, VALID])
    plan = agent._plan("结合库存和采购分析风险", AssistantContext(), uuid.uuid4())
    assert len(plan.agents) == 1 and model.calls == 2
    assert trace.finishes[-1]["output_summary"]["recovery_code"] == "SUPERVISOR_PLAN_PARSE_FAILED"


def test_six_tools_are_repaired_within_one_retry() -> None:
    over_limit = ('{"multi_agent":true,"agents":[{"agent_name":"SupplyAgent",'
                  '"task":"核验供应","tools":["get_part_revisions","get_suppliers",'
                  '"get_supplier_parts","get_inventory","get_purchase_orders",'
                  '"get_purchase_order_records"]}]}')
    agent, model, trace = _agent([over_limit, VALID])
    plan = agent._plan("结合库存和采购分析风险", AssistantContext(), uuid.uuid4())
    assert len(plan.agents[0].tools) == 1
    assert model.calls == 2
    assert "最多 5 个 Tool" in model.prompts[0]
    assert "超过 5 个 Tool" in model.prompts[1]
    assert trace.finishes[-1]["output_summary"]["recovery_code"] == "SUPERVISOR_PLAN_PARSE_FAILED"


def test_clear_full_domain_eol_falls_back_after_two_invalid_plans() -> None:
    agent, model, trace = _agent([INVALID, INVALID])
    plan = agent._plan("综合分析 BRG-6204-A 停产会对公司造成哪些影响？", AssistantContext(), uuid.uuid4())
    assert len(plan.agents) == 4 and model.calls == 2
    assert trace.finishes[-1]["output_summary"]["recovery_code"] == "SUPERVISOR_PLAN_RETRY_FAILED"


def test_ambiguous_query_does_not_fall_back_to_all_agents() -> None:
    agent, model, trace = _agent([INVALID, INVALID])
    with pytest.raises(SupervisorPlanningError, match="重试"):
        agent._plan("分析 BRG-6204-A", AssistantContext(), uuid.uuid4())
    assert model.calls == 2
    assert trace.finishes[-1]["error"] == "SUPERVISOR_PLAN_RETRY_FAILED"


def test_synthesis_invalid_json_retries_once_then_keeps_partial_evidence() -> None:
    agent, model, trace = _agent(["not-json", "still-not-json"])
    agent._assistant = object()
    result, partial = agent._synthesize_traced(
        "分析 BRG-6204-A 供应风险",
        [DomainAgentResult(agent_name=DomainName.SUPPLY, task="核验供应", status="PARTIAL",
                           facts=["已查到库存"], unknowns=["采购查询失败"])],
        [ToolFact("get_inventory", {"part_number": "BRG-6204-A"}, {"rows": [1]})],
        uuid.uuid4(),
    )
    assert partial and model.calls == 2
    assert "部分领域查询失败" in result.judgment
    assert trace.finishes[-1]["error"] == "SUPERVISOR_SYNTHESIS_FAILED"


def test_synthesis_retry_recovers_valid_json() -> None:
    agent, model, trace = _agent([
        "not-json", '{"judgment":"已核验库存，但采购尚未核验。","recommendations":["核验采购"]}',
    ])

    class Grounded:
        def _grounded_analysis(
            self, prose: str, facts: object, question: str, verified_summaries: str = "",
        ) -> bool:
            return True

    agent._assistant = Grounded()
    result, partial = agent._synthesize_traced(
        "分析供应风险",
        [DomainAgentResult(agent_name=DomainName.SUPPLY, task="核验供应", status="SUCCESS",
                           facts=["已查到库存"])],
        [ToolFact("get_inventory", {}, {"rows": [1]})], uuid.uuid4(),
    )
    assert not partial and model.calls == 2
    assert "库存" in result.judgment
    assert trace.finishes[-1]["output_summary"]["recovery_code"] == "SUPERVISOR_SYNTHESIS_PARSE_FAILED"
