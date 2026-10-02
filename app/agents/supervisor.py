"""LLM-directed, bounded collaboration over four read-only domain specialists."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

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
    DomainAssignment,
    DomainName,
    MultiAgentResult,
    SupervisorPlan,
    SupervisorSynthesis,
)
from app.llm.client import LLMClient, LLMResponseError
from app.llm.tracing import trace_scope
from app.services.trace import TraceService

if TYPE_CHECKING:
    from app.agents.enterprise_assistant import EnterpriseAssistant, ToolFact

logger = logging.getLogger(__name__)

_PLAN_PROMPT = """你是 ChangePilot 的只读业务分析 Supervisor。判断用户是否需要跨域/综合业务分析。
简单单项查询或通用知识回答返回 multi_agent=false。复杂供应风险、停产影响、产品影响或跨域分析才返回 true。
仅从 StructureAgent、SupplyAgent、ProductionAgent、DeliveryAgent 中动态选必要 Agent，不要固定全选。
每个 Agent 指定简短子任务和所需只读 Tool 名称；每个 Agent 最多 5 个 Tool，只选完成子任务必需的 Tool，不要执行写操作。
若问题已有明确零件，优先按零件过滤：供应领域使用库存、该零件采购和供应关系；不要查询全量供应商或采购订单。
零件停产的结构影响先用 find_where_used，不要把零件当作 get_bom_structure 的产品根节点。
销售交付只可基于受影响成品版本调用 get_sales_orders_for_products，不要把全公司销售订单当成该零件的交付证据。
StructureAgent: get_part_revisions,get_bom_structure,find_where_used,get_alternatives。
SupplyAgent: get_part_revisions,get_suppliers,get_supplier_parts,get_inventory,get_purchase_orders,get_purchase_order_records。
ProductionAgent: get_part_revisions,get_production_requirements,get_production_orders_for_part,get_production_order_records。
DeliveryAgent: get_sales_orders_for_products,get_sales_order_records。
只返回 JSON：{"multi_agent":true/false,"agents":[{"agent_name":"SupplyAgent","task":"...","tools":["get_inventory"]}]}。"""

_SYNTHESIS_PROMPT = """只根据给出的领域结果做简体中文综合判断与建议，不新增任何企业事实、编号、数量、订单、库存或认证状态。
请在已核验事实基础上给出有用的定性风险判断：可以区分当前需求缓冲与后续补货连续性、已确认影响与待核验风险；不要只重复“需核验”。
若领域查询失败或无数据，应明确保留不确定项，不得补造。不要批准或启动正式 Workflow。
建议可以提出进入正式评估，但不能宣称已批准；回答聚焦业务事实与风险，不复述 Tool 表格。
返回 JSON：{"judgment":"...","recommendations":["..."]}。"""


class SupervisorPlanningError(RuntimeError):
    """Safe, retryable planning failure shown without model output."""


def _full_domain_eol(question: str) -> bool:
    return "综合分析" in question and any(word in question.upper() for word in ("停产", "EOL", "断供")) and "影响" in question


def _fallback_plan() -> SupervisorPlan:
    return SupervisorPlan(multi_agent=True, agents=[
        DomainAssignment(agent_name=name, task="核验该停产事件的本领域影响", tools=[])
        for name in DomainName
    ])


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
        assignments = list(plan.agents)
        if any(item.agent_name == DomainName.DELIVERY for item in assignments):
            assignments.sort(key=lambda item: item.agent_name != DomainName.STRUCTURE)
        for assignment in assignments:
            if assignment.agent_name in selected:
                continue
            selected.append(assignment.agent_name)
            try:
                outcome: DomainOutcome = self._agents[assignment.agent_name].run(
                    assignment, question=question, context=context, run_id=run_id,
                    prior_facts=facts,
                )
            except Exception:
                logger.exception("Domain Agent %s failed", assignment.agent_name)
                results.append(DomainAgentResult(
                    agent_name=assignment.agent_name, task=assignment.task,
                    status="FAILED", unknowns=[f"{assignment.agent_name.value} 查询失败（DOMAIN_AGENT_FAILED）"],
                    tool_calls=assignment.tools,
                ))
                continue
            results.append(outcome.result)
            facts.extend(outcome.tool_facts)
        synthesis, synthesis_partial = self._synthesize(question, results, facts, run_id)
        status = (
            "FAILED" if not facts else
            "PARTIAL" if synthesis_partial or any(item.status != "SUCCESS" for item in results)
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
            try:
                plan = SupervisorPlan.model_validate_json(raw)
                recovery = None
            except ValidationError as first_error:
                logger.warning("Supervisor plan parse failed: %s", first_error.errors(include_input=False))
                too_many_tools = any(
                    item["type"] == "too_long" and "tools" in item["loc"]
                    for item in first_error.errors(include_input=False)
                )
                repair_hint = (
                    "上次某个 Agent 选择了超过 5 个 Tool。每个 Agent 最多保留 5 个，"
                    "按子任务删去非必要 Tool，不要扩大调用范围。"
                    if too_many_tools else "上次 JSON 不符合 schema，请严格按此结构修正。"
                )
                retry = self._llm.generate_json(
                    system_prompt=_PLAN_PROMPT + f"\n{repair_hint}仅返回 JSON。",
                    user_prompt=json.dumps({
                        "question": question,
                        "context": context.model_dump(exclude_none=True),
                        "schema": SupervisorPlan.model_json_schema(),
                        "parse_error": [
                            {"loc": item["loc"], "type": item["type"]}
                            for item in first_error.errors(include_input=False)
                        ],
                    }, ensure_ascii=False),
                )
                try:
                    plan = SupervisorPlan.model_validate_json(retry)
                    recovery = "SUPERVISOR_PLAN_PARSE_FAILED"
                except ValidationError as retry_error:
                    logger.warning("Supervisor plan retry failed: %s", retry_error.errors(include_input=False))
                    if not _full_domain_eol(question):
                        raise SupervisorPlanningError("多领域规划暂时失败，请重试。") from retry_error
                    plan = _fallback_plan()
                    recovery = "SUPERVISOR_PLAN_RETRY_FAILED"
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="SUCCEEDED",
                output_summary={"multi_agent": plan.multi_agent,
                                "agents": [item.agent_name.value for item in plan.agents],
                                "recovery_code": recovery},
            )
            return plan
        except Exception as exc:
            logger.exception("Supervisor planning failed")
            code = (
                "SUPERVISOR_PLAN_RETRY_FAILED" if isinstance(exc, SupervisorPlanningError)
                else "LLM_TIMEOUT" if isinstance(exc, LLMResponseError)
                else "SUPERVISOR_PLAN_PARSE_FAILED"
            )
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="FAILED", error=code,
            )
            raise SupervisorPlanningError("多领域规划暂时失败，请稍后重试。") from exc

    def _synthesize(
        self, question: str, results: list[DomainAgentResult],
        facts: list[ToolFact], run_id: uuid.UUID,
    ) -> tuple[SupervisorSynthesis, bool]:
        with trace_scope("Supervisor Synthesis", {
            "domains": [item.agent_name.value for item in results], "fact_count": len(facts),
        }):
            return self._synthesize_traced(question, results, facts, run_id)

    def _synthesize_traced(
        self, question: str, results: list[DomainAgentResult],
        facts: list[ToolFact], run_id: uuid.UUID,
    ) -> tuple[SupervisorSynthesis, bool]:
        step_id, clock = self._trace.start_step(
            run_id=run_id, node_name="supervisor_summary", agent_name="SupervisorAgent",
            input_summary={"domains": [item.agent_name.value for item in results],
                           "fact_count": len(facts)},
        )
        fallback = SupervisorSynthesis(
            judgment=("部分领域查询失败，本次结论仅基于已成功核验的数据。未核验事项不能作为确定结论。" if facts
                      else "暂无足够经核验的企业事实，无法形成确定结论。"),
            recommendations=["核验不确定项后再决定是否启动正式工程变更流程。"],
        )
        recovery: str | None = None
        try:
            if not facts:
                synthesis = fallback
                recovery = "SUPERVISOR_SYNTHESIS_FAILED"
            else:
                payload = json.dumps({
                    "question": question,
                    "domains": [item.model_dump(exclude={"evidence", "warnings"}) for item in results],
                }, ensure_ascii=False)
                raw = self._llm.generate_json(
                    system_prompt=_SYNTHESIS_PROMPT, user_prompt=payload,
                )
                try:
                    candidate = SupervisorSynthesis.model_validate_json(raw)
                except ValidationError as first_error:
                    logger.warning("Supervisor synthesis parse failed: %s", first_error.errors(include_input=False))
                    retry = self._llm.generate_json(
                        system_prompt=_SYNTHESIS_PROMPT + "\n上次 JSON 无效，请严格按 schema 修正，只返回 JSON。",
                        user_prompt=json.dumps({
                            "evidence": json.loads(payload),
                            "schema": SupervisorSynthesis.model_json_schema(),
                            "parse_error": [
                                {"loc": item["loc"], "type": item["type"]}
                                for item in first_error.errors(include_input=False)
                            ],
                        }, ensure_ascii=False),
                    )
                    candidate = SupervisorSynthesis.model_validate_json(retry)
                    recovery = "SUPERVISOR_SYNTHESIS_PARSE_FAILED"
                prose = " ".join([candidate.judgment, *candidate.recommendations])
                verified_summaries = " ".join(
                    summary for domain in results for summary in domain.facts
                )
                if self._assistant._grounded_analysis(
                    prose, facts, question, verified_summaries,
                ):
                    synthesis = candidate
                else:
                    synthesis = fallback
                    recovery = "SUPERVISOR_SYNTHESIS_FAILED"
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="SUCCEEDED",
                output_summary={"used_fallback": synthesis is fallback, "recovery_code": recovery},
            )
            return synthesis, synthesis is fallback
        except Exception:
            logger.exception("Supervisor synthesis failed")
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="FAILED", error="SUPERVISOR_SYNTHESIS_FAILED",
            )
            return fallback, True
