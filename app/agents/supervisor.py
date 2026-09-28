"""LLM-directed, bounded collaboration over four read-only domain specialists."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.agents.domain import (
    DeliveryAgent,
    DomainOutcome,
    ProductionAgent,
    StructureAgent,
    SupplyAgent,
)
from app.domain.dto.assistant import AssistantContext
from app.domain.dto.multi_agent import (
    DomainAgentResult,
    DomainName,
    MultiAgentResult,
    SupervisorPlan,
    SupervisorSynthesis,
)
from app.llm.client import LLMClient
from app.llm.tracing import trace_scope
from app.services.trace import TraceService

if TYPE_CHECKING:
    from app.agents.enterprise_assistant import EnterpriseAssistant, ToolFact

logger = logging.getLogger(__name__)

_PLAN_PROMPT = """你是 ChangePilot 的只读业务分析 Supervisor。判断用户是否需要跨域/综合业务分析。
简单单项查询或通用知识回答返回 multi_agent=false。复杂供应风险、停产影响、产品影响或跨域分析才返回 true。
仅从 StructureAgent、SupplyAgent、ProductionAgent、DeliveryAgent 中动态选必要 Agent，不要固定全选。
每个 Agent 指定简短子任务和所需只读 Tool 名称；不要执行写操作。
StructureAgent: get_part_revisions,get_bom_structure,find_where_used,get_alternatives。
SupplyAgent: get_part_revisions,get_suppliers,get_supplier_parts,get_inventory,get_purchase_orders,get_purchase_order_records。
ProductionAgent: get_part_revisions,get_production_requirements,get_production_orders_for_part,get_production_order_records。
DeliveryAgent: get_sales_order_records。
只返回 JSON：{"multi_agent":true/false,"agents":[{"agent_name":"SupplyAgent","task":"...","tools":["get_inventory"]}]}。"""

_SYNTHESIS_PROMPT = """只根据给出的领域结果做简体中文综合判断与建议，不新增任何企业事实、编号、数量、订单、库存或认证状态。
若领域查询失败或无数据，应明确保留不确定项，不得补造。不要批准或启动正式 Workflow。
返回 JSON：{"judgment":"...","recommendations":["..."]}。"""


@dataclass(frozen=True)
class SupervisorOutcome:
    result: MultiAgentResult
    tool_facts: list[ToolFact]


class SupervisorAgent:
    """Choose specialists, collect bounded results and synthesize without direct Tools."""

    def __init__(
        self, llm_client: LLMClient, assistant: EnterpriseAssistant,
        trace_service: TraceService,
    ) -> None:
        self._llm = llm_client
        self._assistant = assistant
        self._trace = trace_service
        self._agents = {
            DomainName.STRUCTURE: StructureAgent(assistant, trace_service),
            DomainName.SUPPLY: SupplyAgent(assistant, trace_service),
            DomainName.PRODUCTION: ProductionAgent(assistant, trace_service),
            DomainName.DELIVERY: DeliveryAgent(assistant, trace_service),
        }

    def maybe_run(
        self, question: str, context: AssistantContext, run_id: uuid.UUID,
    ) -> SupervisorOutcome | None:
        with trace_scope("Supervisor", {"question": question[:500]}):
            return self._maybe_run(question, context, run_id)

    def _maybe_run(
        self, question: str, context: AssistantContext, run_id: uuid.UUID,
    ) -> SupervisorOutcome | None:
        plan = self._plan(question, context, run_id)
        if not plan.multi_agent or not plan.agents:
            return None
        selected: list[DomainName] = []
        results: list[DomainAgentResult] = []
        facts: list[ToolFact] = []
        for assignment in plan.agents:
            if assignment.agent_name in selected:
                continue
            selected.append(assignment.agent_name)
            try:
                outcome: DomainOutcome = self._agents[assignment.agent_name].run(
                    assignment, question=question, context=context, run_id=run_id,
                )
            except Exception as exc:
                logger.exception("Domain Agent %s failed", assignment.agent_name)
                results.append(DomainAgentResult(
                    agent_name=assignment.agent_name, task=assignment.task,
                    status="FAILED", unknowns=[f"{assignment.agent_name.value} 查询失败：{exc}"],
                    tool_calls=assignment.tools,
                ))
                continue
            results.append(outcome.result)
            facts.extend(outcome.tool_facts)
        synthesis = self._synthesize(question, results, facts, run_id)
        status = (
            "FAILED" if not facts else
            "PARTIAL" if any(item.status != "SUCCESS" for item in results)
            else "SUCCESS"
        )
        return SupervisorOutcome(MultiAgentResult(
            selected_agents=selected, domains=results,
            judgment=synthesis.judgment,
            recommendations=synthesis.recommendations,
            status=status,
        ), facts)

    def _plan(
        self, question: str, context: AssistantContext, run_id: uuid.UUID,
    ) -> SupervisorPlan:
        step_id, clock = self._trace.start_step(
            run_id=run_id, node_name="supervisor_plan", agent_name="SupervisorAgent",
            input_summary={"question": question[:200]},
        )
        try:
            raw = self._llm.generate_json(
                system_prompt=_PLAN_PROMPT,
                user_prompt=json.dumps({
                    "question": question, "context": context.model_dump(exclude_none=True),
                }, ensure_ascii=False),
            )
            plan = SupervisorPlan.model_validate_json(raw)
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="SUCCEEDED",
                output_summary={"multi_agent": plan.multi_agent,
                                "agents": [item.agent_name.value for item in plan.agents]},
            )
            return plan
        except Exception as exc:
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="FAILED", error=str(exc)[:500],
            )
            raise

    def _synthesize(
        self, question: str, results: list[DomainAgentResult],
        facts: list[ToolFact], run_id: uuid.UUID,
    ) -> SupervisorSynthesis:
        with trace_scope("Supervisor Synthesis", {
            "domains": [item.agent_name.value for item in results], "fact_count": len(facts),
        }):
            return self._synthesize_traced(question, results, facts, run_id)

    def _synthesize_traced(
        self, question: str, results: list[DomainAgentResult],
        facts: list[ToolFact], run_id: uuid.UUID,
    ) -> SupervisorSynthesis:
        step_id, clock = self._trace.start_step(
            run_id=run_id, node_name="supervisor_summary", agent_name="SupervisorAgent",
            input_summary={"domains": [item.agent_name.value for item in results],
                           "fact_count": len(facts)},
        )
        fallback = SupervisorSynthesis(
            judgment=("已取得部分领域事实；未核验事项不能作为确定结论。" if facts
                      else "暂无足够经核验的企业事实，无法形成确定结论。"),
            recommendations=["核验不确定项后再决定是否启动正式工程变更流程。"],
        )
        try:
            if not facts:
                synthesis = fallback
            else:
                raw = self._llm.generate_json(
                    system_prompt=_SYNTHESIS_PROMPT,
                    user_prompt=json.dumps({
                        "question": question,
                        "domains": [item.model_dump(exclude={"evidence"}) for item in results],
                    }, ensure_ascii=False),
                )
                candidate = SupervisorSynthesis.model_validate_json(raw)
                prose = " ".join([candidate.judgment, *candidate.recommendations])
                synthesis = (
                    candidate if self._assistant._grounded_analysis(prose, facts, question)
                    else fallback
                )
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="SUCCEEDED",
                output_summary={"used_fallback": synthesis is fallback},
            )
            return synthesis
        except Exception as exc:
            logger.exception("Supervisor synthesis failed")
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="FAILED", error=str(exc)[:500],
            )
            return fallback
