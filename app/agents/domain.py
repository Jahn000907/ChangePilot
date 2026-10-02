"""Bounded domain specialists over the existing read-only application Tools."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from app.agents.assistant_queries import extract_entities
from app.core.business_display import business_value
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
    DomainName.DELIVERY: frozenset({"find_where_used", "get_sales_orders_for_products", "get_sales_order_records"}),
}

_DEFAULT_TOOLS: dict[DomainName, tuple[str, ...]] = {
    DomainName.STRUCTURE: ("find_where_used", "get_alternatives"),
    DomainName.SUPPLY: ("get_supplier_parts", "get_inventory", "get_purchase_orders"),
    DomainName.PRODUCTION: ("get_production_requirements",),
    DomainName.DELIVERY: ("get_sales_orders_for_products",),
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
        prior_facts: list[ToolFact] | None = None,
    ) -> DomainOutcome:
        with trace_scope(self.name.value, {"task": assignment.task[:200], "tools": assignment.tools}):
            return self._run(assignment, question=question, context=context, run_id=run_id,
                             prior_facts=prior_facts or [])

    def _run(
        self, assignment: DomainAssignment, *, question: str,
        context: AssistantContext, run_id: uuid.UUID, prior_facts: list[ToolFact],
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
        warnings: list[str] = []
        missing_required: list[str] = []
        attempted: list[str] = []
        try:
            entities = extract_entities(question)
            selected, required = self._select_tools(assignment, question)
            with self._trace.bind_step(step_id):
                tool_map = {tool.name: tool for tool in self._assistant._tools}
                for name in selected:
                    attempted.append(name)
                    try:
                        if name == "get_sales_orders_for_products":
                            references = self._affected_products(prior_facts)
                            if not references:
                                lookup = self._assistant._arguments(
                                    "find_where_used", question, entities, context,
                                    tool_map, run_id, agent_name=self.name.value,
                                )
                                attempted.append("find_where_used")
                                message, succeeded = self._assistant._invoke_tool(
                                    "find_where_used", lookup, tool_map, run_id,
                                    agent_name=self.name.value,
                                )
                                if succeeded:
                                    from app.agents.enterprise_assistant import ToolFact
                                    structure = ToolFact("find_where_used", lookup, self._assistant._data(message))
                                    references = self._affected_products([structure])
                            if not references:
                                raise ValueError("受影响成品版本尚未核验")
                            arguments = {"product_references": references}
                        else:
                            arguments = self._assistant._arguments(
                                name, question, entities, context, tool_map, run_id,
                                agent_name=self.name.value,
                            )
                            if name == "get_purchase_orders":
                                arguments["open_only"] = True
                    except (ValueError, RuntimeError) as exc:
                        self._gap(name, f"{name} 参数或版本无法确认：{exc}", required,
                                  unknowns, warnings, missing_required)
                        continue
                    message, succeeded = self._assistant._invoke_tool(
                        name, arguments, tool_map, run_id, agent_name=self.name.value,
                    )
                    if not succeeded:
                        self._gap(name, f"{name} 查询失败，相关事实尚未核验。", required,
                                  unknowns, warnings, missing_required)
                        continue
                    data = self._assistant._data(message)
                    if data is None:
                        self._gap(name, f"{name} 结果无法读取，相关事实尚未核验。", required,
                                  unknowns, warnings, missing_required)
                        continue
                    from app.agents.enterprise_assistant import ToolFact

                    fact = ToolFact(name, arguments, data)
                    self._assistant._update_context(context, fact)
                    if self._assistant._empty_fact(fact):
                        # A successful empty query verifies absence; it is not a failed lookup.
                        facts.append(fact)
                        evidence.append(DomainEvidence(
                            tool_name=name, arguments=arguments,
                            summary=self._assistant._format_fact(fact, question)[:4000],
                        ))
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
                            warnings.append("零件当前有效版本尚未唯一确认。")
            status = (
                "PARTIAL" if facts and missing_required else "SUCCESS" if facts else
                "FAILED" if any("失败" in item or "无法" in item for item in unknowns)
                else "NO_DATA"
            )
            label = _DOMAIN_LABELS[self.name]
            result = DomainAgentResult(
                agent_name=self.name, task=assignment.task, status=status,
                facts=[self._summarize(fact) for fact in facts], evidence=evidence,
                risks=self._risks(facts),
                unknowns=unknowns, warnings=warnings, missing_required=missing_required,
                recommendations=[f"核对{label}后再决定正式变更处置。"] if facts else [],
                tool_calls=attempted,
            )
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="SUCCEEDED" if facts else "FAILED",
                output_summary={"status": status, "tool_calls": attempted,
                                "fact_count": len(facts), "unknown_count": len(unknowns),
                                "warnings": warnings[:5], "missing_required": missing_required},
            )
            return DomainOutcome(result, facts)
        except Exception as exc:
            self._trace.finish_step(
                step_id=step_id, started_clock=clock, status="FAILED", error=str(exc)[:500],
            )
            raise

    def _risks(self, facts: list[ToolFact]) -> list[str]:
        names = {fact.name for fact in facts if not self._assistant._empty_fact(fact)}
        risks: list[str] = []
        if self.name == DomainName.SUPPLY:
            if "get_purchase_orders" in names:
                risks.append("采购订单事实提示后续补货需核验交付兑现；停产情景下不能仅凭在途订单认定供给可靠。")
            if "get_inventory" in names:
                risks.append("当前库存可提供短期缓冲，但不能单独证明长期供应连续性。")
        elif self.name == DomainName.PRODUCTION and "get_production_requirements" in names:
            risks.append("已识别生产物料需求；供应中断可能影响对应订单，应核对需求与可用供给。")
        elif self.name == DomainName.STRUCTURE and "find_where_used" in names:
            risks.append("已识别使用该零件的产品；替代或停供可能波及这些产品的结构与交付。")
        elif self.name == DomainName.DELIVERY and "get_sales_orders_for_products" in names:
            risks.append("相关销售订单存在交付敞口；实际延期需结合供给与排产核验。")
        return risks

    def _select_tools(self, assignment: DomainAssignment, question: str) -> tuple[list[str], set[str]]:
        allowed = DOMAIN_TOOLS[self.name]
        selected = list(dict.fromkeys(assignment.tools or _DEFAULT_TOOLS[self.name]))
        if not selected or any(name not in allowed for name in selected):
            raise ValueError(f"{self.name.value} 收到超出权限的 Tool 计划")
        entities = extract_entities(question)
        part = bool(entities.parts)
        if not part:
            return selected, set(selected)
        if self.name == DomainName.STRUCTURE:
            selected = ["find_where_used", *(
                name for name in selected
                if name != "find_where_used" and (name != "get_bom_structure" or entities.products)
            )]
            required = {"find_where_used"}
        elif self.name == DomainName.SUPPLY:
            selected = ["get_inventory", "get_purchase_orders", "get_supplier_parts", *(
                name for name in selected if name not in {
                    "get_inventory", "get_purchase_orders", "get_supplier_parts", "get_suppliers",
                    "get_purchase_order_records",
                }
            )]
            if entities.supplier_code and "get_suppliers" in assignment.tools:
                selected.append("get_suppliers")
            if entities.purchase_order and "get_purchase_order_records" in assignment.tools:
                selected.append("get_purchase_order_records")
            required = {"get_inventory", "get_purchase_orders"}
        elif self.name == DomainName.PRODUCTION:
            selected = ["get_production_requirements", *(
                name for name in selected if name not in {
                    "get_production_requirements", "get_production_order_records",
                }
            )]
            if entities.production_order and "get_production_order_records" in assignment.tools:
                selected.append("get_production_order_records")
            required = {"get_production_requirements"}
        else:
            selected = ["get_sales_orders_for_products"]
            required = {"get_sales_orders_for_products"}
        return list(dict.fromkeys(selected)), required

    @staticmethod
    def _gap(name: str, message: str, required: set[str], unknowns: list[str],
             warnings: list[str], missing_required: list[str]) -> None:
        if name in required:
            unknowns.append(message)
            missing_required.append(name)
        else:
            warnings.append(message)

    @staticmethod
    def _affected_products(facts: list[ToolFact]) -> list[tuple[str, str]]:
        for fact in facts:
            if fact.name != "find_where_used" or not isinstance(fact.data, dict):
                continue
            products = set(fact.data.get("products", []))
            references = {
                (row["ancestor_part_number"], row["ancestor_revision_code"])
                for row in fact.data.get("rows", []) if isinstance(row, dict)
                and row.get("ancestor_part_number") in products
                and row.get("ancestor_revision_code")
            }
            return sorted(references)
        return []

    @staticmethod
    def _summarize(fact: ToolFact) -> str:
        data = fact.data
        rows = data.get("rows", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        rows = [row for row in rows if isinstance(row, dict)]
        number = str(fact.arguments.get("part_number", "该零件"))
        def fmt(value: object) -> str:
            return format(Decimal(str(value)).normalize(), "f")
        if fact.name == "find_where_used" and not data.get("products"):
            return f"当前有效结构中未查到使用 {number} 的成品。"
        if not rows and fact.name in {"get_inventory", "get_purchase_orders", "get_supplier_parts",
                                      "get_alternatives", "get_production_requirements",
                                      "get_sales_orders_for_products"}:
            label = {
                "get_inventory": "库存", "get_purchase_orders": "未完成采购订单",
                "get_supplier_parts": "供应关系", "get_alternatives": "替代料",
                "get_production_requirements": "生产需求",
                "get_sales_orders_for_products": "受影响成品销售订单",
            }[fact.name]
            return f"{number} 的{label}查询成功，暂无符合条件的记录。"
        if fact.name == "find_where_used":
            return f"{number} 影响 {len(data['products'])} 个成品：{'、'.join(data['products'])}。"
        if fact.name == "get_inventory":
            available = sum(Decimal(str(row["qty_on_hand"])) - Decimal(str(row["qty_reserved"])) for row in rows)
            return f"{number} 当前可用库存 {fmt(available)}。"
        if fact.name == "get_purchase_orders":
            ordered = sum(Decimal(str(row["ordered_qty"])) for row in rows)
            received = sum(Decimal(str(row["received_qty"])) for row in rows)
            statuses = "、".join(sorted({business_value(row["po_status"]) for row in rows}))
            return (f"{number} 有 {len(rows)} 条未完成采购订单行：订购 {fmt(ordered)}，"
                    f"已收 {fmt(received)}，未收 {fmt(ordered - received)}；状态：{statuses}。")
        if fact.name == "get_supplier_parts":
            return "供应关系：" + "；".join(
                f"{row['supplier_code']} {row['supplier_name']}（{business_value(row['status'])}，"
                f"{business_value(row['qualification_status'])}）" for row in rows
            ) + "。"
        if fact.name == "get_alternatives":
            return "替代料：" + "；".join(
                f"{row['alternative_part_number']}（{business_value(row['qualification_status'])}）"
                for row in rows
            ) + "。"
        if fact.name == "get_production_requirements":
            active = [row for row in rows if row.get("order_status") not in {"COMPLETED", "CANCELLED"}]
            orders = {row["order_number"] for row in active}
            demand = sum(Decimal(str(row["required_qty"])) for row in active)
            products = sorted({row["product_part_number"] for row in active})
            return (f"{number} 当前涉及 {len(orders)} 个活动生产订单，有效需求 {fmt(demand)}；"
                    f"相关产品：{'、'.join(products)}。")
        if fact.name == "get_sales_orders_for_products":
            orders = {row["order_number"] for row in rows}
            products = sorted({row["product_part_number"] for row in rows})
            statuses = "、".join(sorted({business_value(row["order_status"]) for row in rows}))
            return (f"受影响成品 {'、'.join(products)} 关联 {len(orders)} 个销售订单"
                    f"（{len(rows)} 行）；状态：{statuses}。")
        return f"{fact.name} 已核验 {len(rows)} 条相关记录。"


class StructureAgent(DomainAgent):
    name = DomainName.STRUCTURE


class SupplyAgent(DomainAgent):
    name = DomainName.SUPPLY


class ProductionAgent(DomainAgent):
    name = DomainName.PRODUCTION


class DeliveryAgent(DomainAgent):
    name = DomainName.DELIVERY
