"""Bounded domain specialists over the existing read-only application Tools."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.agents.assistant_queries import extract_entities
from app.domain.dto.assistant import AssistantContext
from app.domain.dto.multi_agent import (
    DomainAgentResult,
    DomainAssignment,
    DomainEvidence,
    DomainName,
)
from app.llm.tracing import trace_scope
from app.services.trace import TraceService

if TYPE_CHECKING:
    from app.agents.enterprise_assistant import EnterpriseAssistant, ToolFact


_COMMON = frozenset({"get_part_revisions"})
DOMAIN_TOOLS: dict[DomainName, frozenset[str]] = {
    DomainName.STRUCTURE: _COMMON | frozenset({
        "get_bom_structure", "find_where_used", "get_alternatives",
    }),
    DomainName.SUPPLY: _COMMON | frozenset({
        "get_suppliers", "get_supplier_parts", "get_inventory",
        "get_purchase_orders", "get_purchase_order_records",
    }),
    DomainName.PRODUCTION: _COMMON | frozenset({
        "get_production_requirements", "get_production_orders_for_part",
        "get_production_order_records",
    }),
    DomainName.DELIVERY: frozenset({"get_sales_order_records"}),
}

_DEFAULT_TOOLS: dict[DomainName, tuple[str, ...]] = {
    DomainName.STRUCTURE: ("find_where_used", "get_alternatives"),
    DomainName.SUPPLY: ("get_supplier_parts", "get_inventory", "get_purchase_orders"),
    DomainName.PRODUCTION: ("get_production_requirements",),
    DomainName.DELIVERY: ("get_sales_order_records",),
}

_DOMAIN_LABELS = {
    DomainName.STRUCTURE: "产品结构",
    DomainName.SUPPLY: "供应与采购",
    DomainName.PRODUCTION: "生产",
    DomainName.DELIVERY: "销售交付",
}


@dataclass(frozen=True)
class DomainOutcome:
    result: DomainAgentResult
    tool_facts: list[ToolFact]


class DomainAgent:
    """Select several owned Tools, summarize verified facts and flag gaps."""

    name: DomainName

    def __init__(
        self, assistant: EnterpriseAssistant, trace_service: TraceService,
    ) -> None:
        self._assistant = assistant
        self._trace = trace_service

    def run(
        self, assignment: DomainAssignment, *, question: str,
        context: AssistantContext, run_id: uuid.UUID,
    ) -> DomainOutcome:
        with trace_scope(self.name.value, {"task": assignment.task[:200], "tools": assignment.tools}):
            return self._run(assignment, question=question, context=context, run_id=run_id)

    def _run(
        self, assignment: DomainAssignment, *, question: str,
        context: AssistantContext, run_id: uuid.UUID,
    ) -> DomainOutcome:
        if assignment.agent_name != self.name:
            raise ValueError("领域任务与 Agent 不匹配")
        step_id, clock = self._trace.start_step(
            run_id=run_id, node_name=self.name.value, agent_name=self.name.value,
            input_summary={"task": assignment.task[:200], "requested_tools": assignment.tools},
        )
        facts: list[ToolFact] = []
        evidence: list[DomainEvidence] = []
        unknowns: list[str] = []
        attempted: list[str] = []
        try:
            selected = self._select_tools(assignment)
            with self._trace.bind_step(step_id):
                entities = extract_entities(question)
                tool_map = {tool.name: tool for tool in self._assistant._tools}
                for name in selected:
                    attempted.append(name)
                    try:
                        arguments = self._assistant._arguments(
                            name, question, entities, context, tool_map, run_id,
                            agent_name=self.name.value,
                        )
                    except (ValueError, RuntimeError) as exc:
                        unknowns.append(f"{name} 参数或版本无法确认：{exc}")
                        continue
                    message, succeeded = self._assistant._invoke_tool(
                        name, arguments, tool_map, run_id, agent_name=self.name.value,
                    )
                    if not succeeded:
                        unknowns.append(f"{name} 查询失败，相关事实尚未核验。")
                        continue
                    data = self._assistant._data(message)
                    if data is None:
                        unknowns.append(f"{name} 结果无法读取，相关事实尚未核验。")
                        continue
                    from app.agents.enterprise_assistant import ToolFact

                    fact = ToolFact(name, arguments, data)
                    self._assistant._update_context(context, fact)
                    if self._assistant._empty_fact(fact):
                        unknowns.append(f"{name} 查询成功但暂无符合条件的数据。")
                        continue
                    facts.append(fact)
                    evidence.append(DomainEvidence(
                        tool_name=name, arguments=arguments,
                        summary=self._assistant._format_fact(fact, question)[:4000],
                    ))
                    if (name == "get_supplier_parts" and entities.parts
                            and context.current_revision is None):
                        try:
                            context.current_revision = self._assistant._revision(
                                entities.parts[0], entities, context, tool_map, run_id,
                                agent_name=self.name.value,
                            )
                        except (ValueError, RuntimeError):
                            unknowns.append("零件当前有效版本尚未唯一确认。")
                if self.name == DomainName.DELIVERY and evidence:
                    unknowns.append("销售订单与目标零件的直接关联仍需结合产品结构核验。")
            status = (
                "PARTIAL" if facts and unknowns else "SUCCESS" if facts else
                "FAILED" if any("失败" in item or "无法" in item for item in unknowns)
                else "NO_DATA"
            )
            label = _DOMAIN_LABELS[self.name]
            result = DomainAgentResult(
                agent_name=self.name, task=assignment.task, status=status,
                facts=[item.summary for item in evidence], evidence=evidence,
                risks=[f"{label}风险需结合已核验事实评估。"] if facts else [],
                unknowns=unknowns,
                recommendations=[f"核对{label}后再决定正式变更处置。"] if facts else [],
                tool_calls=attempted,
            )
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="SUCCEEDED" if facts else "FAILED",
                output_summary={"status": status, "tool_calls": attempted,
                                "fact_count": len(facts), "unknown_count": len(unknowns)},
            )
            return DomainOutcome(result, facts)
        except Exception as exc:
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="FAILED", error=str(exc)[:500],
            )
            raise

    def _select_tools(self, assignment: DomainAssignment) -> list[str]:
        allowed = DOMAIN_TOOLS[self.name]
        selected = list(dict.fromkeys(assignment.tools or _DEFAULT_TOOLS[self.name]))
        if not selected or any(name not in allowed for name in selected):
            raise ValueError(f"{self.name.value} 收到超出权限的 Tool 计划")
        return selected


class StructureAgent(DomainAgent):
    name = DomainName.STRUCTURE


class SupplyAgent(DomainAgent):
    name = DomainName.SUPPLY


class ProductionAgent(DomainAgent):
    name = DomainName.PRODUCTION


class DeliveryAgent(DomainAgent):
    name = DomainName.DELIVERY
