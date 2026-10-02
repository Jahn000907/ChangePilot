"""Grounded employee queries with deterministic Tool arguments."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.agents.assistant_queries import (
    QueryEntities,
    clear_intent,
    extract_entities,
    substitution_pair,
)
from app.core.business_display import business_value
from app.core.business_time import shanghai_datetime
from app.domain.dto.assistant import AssistantContext
from app.domain.dto.multi_agent import MultiAgentResult
from app.llm.client import DeepSeekLLMClient, ToolCallingLLMClient
from app.llm.tracing import trace_scope
from app.services.trace import TraceService
from app.tools.langchain import get_enterprise_tools

logger = logging.getLogger(__name__)

_PROMPT = """你是 ChangePilot 企业智能助手，优先用简体中文自然回答。
你具备通用大模型能力：一般知识、概念解释、总结、改写、翻译和写作可直接回答，无需 Tool。
涉及本企业当前 BOM、Where-Used、替代料资格、库存、供应商及供应关系、采购/生产/销售订单或工程变更状态时，必须先调用对应只读 Tool；不得凭模型知识、会话记忆或上下文编造企业事实。
混合问题先调用所有必要 Tool，再基于本轮成功结果给出有用的定性判断；区分企业事实、分析判断、不确定项和建议动作。
可以分析当前需求缓冲与后续补货连续性等关系，不要只重复“需进一步核验”；不得新增未核验编号、数量、百分比或交期。不显示 Tool JSON。
Tool 失败或无数据时不得补造事实，也不得换用其他数据口径。Tool 参数由系统核对，不得猜版本、日期或编号。不得修改业务数据或自动启动正式流程。"""

_PART_TOOLS = {
    "find_where_used", "get_inventory", "get_purchase_orders", "get_alternatives",
    "get_production_requirements", "get_production_orders_for_part",
}
_STRUCTURE_TOOLS = {"find_where_used", "get_bom_structure"}
_REVISION_TOOLS = _PART_TOOLS - {"get_production_orders_for_part"} | {"get_bom_structure"}
_DISPLAY_NAMES = {
    "supplier_code": "供应商编号", "supplier_name": "供应商", "part_number": "零件号",
    "revision_code": "版本", "order_number": "订单号", "po_number": "采购订单号",
    "product_part_number": "产品编号", "product_revision": "产品版本",
    "status": "状态", "po_status": "订单状态", "line_status": "行状态",
    "qualification_status": "资格状态", "ordered_qty": "订购数量",
    "received_qty": "已收数量", "required_qty": "需求数量",
    "reserved_qty": "预留数量", "issued_qty": "已发数量",
    "qty_on_hand": "现有量", "qty_reserved": "预留量",
    "planned_qty": "计划数量", "completed_qty": "完成数量",
    "unit_price": "单价", "unit_cost": "单位成本", "currency": "币种",
    "expected_date": "预计日期", "order_date": "下单日期",
    "planned_start": "计划开始", "planned_end": "计划结束",
    "last_time_buy_date": "最后采购日", "eol_date": "停产日",
    "alternative_part_number": "替代零件号", "alternative_revision_code": "替代版本",
    "manufacturer_part_number": "制造商料号", "lead_time_days": "交期（天）",
    "minimum_order_qty": "最小订购量", "line_number": "行号",
}
@dataclass(frozen=True)
class ToolFact:
    name: str
    arguments: dict[str, object]
    data: object


@dataclass(frozen=True)
class AssistantAnswer:
    text: str
    tool_names: list[str]
    context: AssistantContext
    facts: list[ToolFact]
    failed: bool = False
    status: str = "SUCCESS"


class QueryResolutionError(ValueError):
    """Missing or ambiguous user-controlled query identity."""


class ToolQueryError(RuntimeError):
    """A required read Tool failed before the requested fact could be checked."""


class NoBusinessDataError(ValueError):
    """The read Tool succeeded but found no effective business record."""


class EnterpriseAssistant:
    def __init__(
        self, llm_client: ToolCallingLLMClient | None = None,
        tools: Sequence[BaseTool] | None = None,
        trace_service: TraceService | None = None,
        max_rounds: int = 5,
    ) -> None:
        self._client = llm_client
        self._tools = list(tools) if tools is not None else get_enterprise_tools()
        self._trace = trace_service or TraceService()
        self._max_rounds = max_rounds

    def answer(
        self, question: str, context: AssistantContext,
        history: list[tuple[str, str]], run_id: uuid.UUID,
    ) -> AssistantAnswer:
        with trace_scope("Enterprise Assistant", {"question": question[:500], "run_id": str(run_id)}):
            return self._answer(question, context, history, run_id)

    def _answer(
        self, question: str, context: AssistantContext,
        history: list[tuple[str, str]], run_id: uuid.UUID,
    ) -> AssistantAnswer:
        entities = extract_entities(question)
        tool_map = {tool.name: tool for tool in self._tools}
        intent = clear_intent(question, entities, context)
        facts: list[ToolFact] = []

        # Clear single-fact questions do not need a model to invent Tool arguments.
        if intent:
            try:
                arguments = self._arguments(intent, question, entities, context, tool_map, run_id)
            except ToolQueryError as exc:
                return AssistantAnswer(str(exc), [], context, facts, True, "TOOL_ERROR")
            except NoBusinessDataError as exc:
                return AssistantAnswer(str(exc), [], context, facts, status="NO_DATA")
            except QueryResolutionError as exc:
                return AssistantAnswer(str(exc), [], context, facts, status="MISSING_INPUT")
            result, succeeded = self._invoke_tool(intent, arguments, tool_map, run_id)
            if not succeeded:
                return AssistantAnswer("业务查询失败，请稍后重试。", [], context, facts, True, "TOOL_ERROR")
            data = self._data(result)
            if data is None:
                return AssistantAnswer("业务查询返回的结果无法读取，请稍后重试。", [], context, facts, True, "TOOL_ERROR")
            fact = ToolFact(intent, arguments, data)
            facts.append(fact)
            self._update_context(context, fact)
            if intent == "get_bom_structure" and "其中" in question and len(entities.parts) == 1:
                context.current_part = entities.parts[0]
                context.current_focus = "part"
                context.current_revision = None
            if intent == "get_supplier_parts" and isinstance(arguments.get("part_number"), str):
                try:
                    context.current_revision = self._revision(
                        str(arguments["part_number"]), entities, context, tool_map, run_id,
                    )
                except (QueryResolutionError, ToolQueryError, NoBusinessDataError):
                    context.current_revision = None
            return AssistantAnswer(
                self._format_fact(fact, question), [intent], context, facts,
                status="NO_DATA" if self._empty_fact(fact) else "SUCCESS",
            )

        client = self._client or DeepSeekLLMClient()
        if (not self._general_answer_allowed(question, entities)
                and callable(getattr(client, "generate_json", None))):
            from app.agents.supervisor import SupervisorAgent

            coordinated = SupervisorAgent(client, self, self._trace).maybe_run(
                question, context, run_id,
            )
            if coordinated is not None:
                result = coordinated.result
                return AssistantAnswer(
                    self._format_multi_agent(result),
                    [name for domain in result.domains for name in domain.tool_calls],
                    context, coordinated.tool_facts,
                    failed=result.status != "SUCCESS",
                    status=("SUCCESS" if result.status == "SUCCESS" else
                            "PARTIAL" if result.status == "PARTIAL" else "TOOL_ERROR"),
                )

        messages: list[BaseMessage] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(content="当前会话上下文（不是业务事实）：" + context.model_dump_json()),
        ]
        for role, content in history[-12:]:
            messages.append(HumanMessage(content=content) if role == "user" else AIMessage(content=content))
        messages.append(HumanMessage(content=question))
        resolution_error: str | None = None
        resolution_status = "MISSING_INPUT"
        tool_failed = False
        no_data = False
        for _ in range(self._max_rounds):
            response = client.invoke_with_tools(messages=messages, tools=self._tools)
            messages.append(response)
            if response.tool_calls:
                for call in response.tool_calls:
                    name = str(call["name"])
                    try:
                        arguments = self._arguments(
                            name, question, entities, context, tool_map, run_id
                        )
                    except (ToolQueryError, NoBusinessDataError) as exc:
                        tool_failed = isinstance(exc, ToolQueryError)
                        resolution_error = str(exc)
                        resolution_status = "TOOL_ERROR" if tool_failed else "NO_DATA"
                        messages.append(ToolMessage(
                            content=json.dumps({"error": resolution_error}, ensure_ascii=False),
                            tool_call_id=str(call["id"]), name=name, status="error",
                        ))
                        continue
                    except QueryResolutionError as exc:
                        resolution_error = str(exc)
                        messages.append(ToolMessage(
                            content=json.dumps({"error": resolution_error}, ensure_ascii=False),
                            tool_call_id=str(call["id"]), name=name, status="error",
                        ))
                        continue
                    result, succeeded = self._invoke_tool(
                        name, arguments, tool_map, run_id, call_id=str(call["id"])
                    )
                    messages.append(result)
                    if not succeeded:
                        tool_failed = True
                        continue
                    data = self._data(result)
                    if data is None:
                        tool_failed = True
                        continue
                    fact = ToolFact(name, arguments, data)
                    facts.append(fact)
                    no_data = no_data or self._empty_fact(fact)
                    self._update_context(context, fact)
                continue
            if tool_failed:
                return AssistantAnswer("部分业务查询失败，无法可靠回答。请稍后重试。", [], context, facts, True, "TOOL_ERROR")
            business_facts = [fact for fact in facts if fact.name != "get_part_revisions"]
            if not business_facts:
                if self._general_answer_allowed(question, entities):
                    content = str(response.content).strip()
                    if content:
                        return AssistantAnswer(content, [], context, facts)
                if resolution_error:
                    return AssistantAnswer(
                        resolution_error, [], context, facts,
                        status=resolution_status,
                    )
                if entities.parts or entities.products or entities.purchase_order or entities.production_order or entities.sales_order or entities.supplier_code or self._business_reference(question):
                    return AssistantAnswer("未取得这项业务查询的结果，请明确要查询的数据类型后重试。", [], context, facts, True, "TOOL_ERROR")
                return AssistantAnswer("请提供要查询的产品、零件、供应商或订单编号。", [], context, facts, status="MISSING_INPUT")
            missing = self._missing_requested_facts(question, business_facts)
            if missing:
                return AssistantAnswer(
                    "所需业务事实尚未全部核验，无法可靠分析；请稍后重试。",
                    [fact.name for fact in business_facts], context, facts, True, "TOOL_ERROR",
                )
            # Always expose verified facts separately; model prose is only analysis.
            fact_text = "\n\n".join(self._format_fact(fact, question) for fact in business_facts)
            if no_data:
                return AssistantAnswer(
                    fact_text, [fact.name for fact in business_facts], context, facts,
                    status="NO_DATA" if all(self._empty_fact(fact) for fact in business_facts) else "SUCCESS",
                )
            analysis = str(response.content).strip()
            if self._mixed_analysis_requested(question) and analysis and self._grounded_analysis(
                analysis, business_facts, question,
            ):
                fact_text = f"企业事实：\n\n{fact_text}\n\n分析判断：\n\n{analysis}"
            return AssistantAnswer(
                fact_text,
                [fact.name for fact in business_facts], context, facts,
                status="SUCCESS",
            )
        raise RuntimeError("智能助手查询轮次已达上限，请缩小问题范围后重试。")

    def _arguments(
        self, name: str, question: str, entities: QueryEntities,
        context: AssistantContext, tool_map: dict[str, BaseTool], run_id: uuid.UUID,
        *, agent_name: str = "EnterpriseAssistant",
    ) -> dict[str, object]:
        # LLM-provided arguments are intentionally ignored for identity, revision and date.
        if name not in tool_map:
            raise ToolQueryError("业务查询失败：未知或非只读 Tool。")
        if name == "get_bom_structure":
            if "其中" in question and context.current_product and not entities.products:
                target = context.current_product
            else:
                target = self._subject(
                    entities.products or entities.parts,
                    context.current_product if not entities.parts else None,
                    "产品或组件编号",
                )
        elif name in _PART_TOOLS:
            pair = substitution_pair(question) if name == "get_alternatives" else None
            target = pair[0] if pair else self._subject(
                entities.parts,
                context.current_part if context.current_focus == "part" else None,
                "零件号",
            )
        elif name == "get_part_revisions":
            explicit = entities.parts or entities.products
            remembered = (
                context.current_part if context.current_focus == "part"
                else context.current_product if context.current_focus == "product"
                else None
            )
            target = self._subject(explicit, remembered, "零件或产品编号")
            return {"part_number": target, **self._date_argument(entities)}
        elif name == "get_supplier_parts":
            return {
                "supplier": entities.supplier_code or entities.supplier_name or (
                    context.current_supplier_code or context.current_supplier_name
                    if not entities.parts else None
                ),
                "part_number": self._optional_subject(
                    entities.parts,
                    context.current_part if not (entities.supplier_code or entities.supplier_name) else None,
                ),
            }
        elif name == "get_suppliers":
            return {"search": entities.supplier_code or entities.supplier_name or context.current_supplier_code or context.current_supplier_name}
        elif name == "get_purchase_order_records":
            return {
                "order_number": entities.purchase_order or (
                    context.current_purchase_order if not entities.supplier_code else None
                ),
                "open_only": self._open_purchase(question),
                "supplier_code": (
                    entities.supplier_code or context.current_supplier_code
                    if not entities.purchase_order else None
                ),
            }
        elif name == "get_production_order_records":
            return {"order_number": entities.production_order or context.current_production_order}
        elif name == "get_sales_order_records":
            return {"order_number": entities.sales_order or context.current_sales_order}
        else:
            raise QueryResolutionError("查询失败：无法确定该 Tool 的安全参数。")
        arguments: dict[str, object] = {"part_number": target}
        if name in _REVISION_TOOLS:
            try:
                arguments["revision_code"] = self._revision(
                    target, entities, context, tool_map, run_id, agent_name=agent_name,
                )
            except NoBusinessDataError:
                if name != "get_inventory":
                    raise
                # An unknown candidate still deserves a real inventory lookup.
                arguments["revision_code"] = None
        if name in _STRUCTURE_TOOLS:
            arguments.update(self._date_argument(entities))
        if name == "get_purchase_orders":
            arguments["open_only"] = self._open_purchase(question)
        return arguments

    def _revision(
        self, target: str, entities: QueryEntities, context: AssistantContext,
        tool_map: dict[str, BaseTool], run_id: uuid.UUID,
        *, agent_name: str = "EnterpriseAssistant",
    ) -> str:
        if entities.revision and len(entities.parts + entities.products) <= 1:
            return entities.revision
        focused = (
            context.current_part if context.current_focus == "part"
            else context.current_product if context.current_focus == "product"
            else None
        )
        if entities.as_of_date is None and focused == target and context.current_revision:
            return context.current_revision
        result, succeeded = self._invoke_tool(
            "get_part_revisions", {"part_number": target, **self._date_argument(entities)},
            tool_map, run_id, agent_name=agent_name,
        )
        if not succeeded:
            raise ToolQueryError("业务查询失败：无法核对当前有效版本。")
        data = self._data(result)
        if not isinstance(data, dict):
            raise ToolQueryError("业务查询失败：版本查询结果无效。")
        revisions = data.get("effective_revisions")
        if not isinstance(revisions, list) or not revisions:
            raise NoBusinessDataError("暂无当前有效版本；如需历史查询，请指定日期和版本。")
        if len(revisions) != 1:
            raise QueryResolutionError("存在多个当前有效版本，请指定要查询的版本。")
        return str(revisions[0])

    def _invoke_tool(
        self, name: str, arguments: dict[str, object],
        tool_map: dict[str, BaseTool], run_id: uuid.UUID, *, call_id: str | None = None,
        agent_name: str = "EnterpriseAssistant",
    ) -> tuple[ToolMessage, bool]:
        identifier = call_id or uuid.uuid4().hex
        handle = self._trace.start_tool_call(
            run_id=run_id, tool_name=name, arguments=arguments,
            agent_name=agent_name,
        )
        try:
            result = tool_map[name].invoke({
                "name": name, "args": arguments, "id": identifier, "type": "tool_call",
            })
            if not isinstance(result, ToolMessage):
                raise TypeError("Tool 未返回结构化消息")
            succeeded = result.status != "error"
        except Exception:
            logger.exception("Enterprise Assistant Tool %s failed", name)
            result = ToolMessage(
                content=json.dumps({"error": "查询失败"}, ensure_ascii=False),
                tool_call_id=identifier, name=name, status="error",
            )
            succeeded = False
        self._trace.finish_tool_call(
            handle, status="SUCCEEDED" if succeeded else "FAILED",
            result_summary={"content_preview": str(result.content)[:500]},
        )
        return result, succeeded

    @staticmethod
    def _subject(explicit: tuple[str, ...], remembered: str | None, label: str) -> str:
        if len(explicit) > 1:
            raise QueryResolutionError(f"识别到多个{label}，请明确本次查询对象。")
        target = explicit[0] if explicit else remembered
        if target is None:
            raise QueryResolutionError(f"请提供要查询的{label}。")
        return target

    @staticmethod
    def _optional_subject(explicit: tuple[str, ...], remembered: str | None) -> str | None:
        if len(explicit) > 1:
            raise QueryResolutionError("识别到多个零件号，请明确本次查询对象。")
        return explicit[0] if explicit else remembered

    @staticmethod
    def _date_argument(entities: QueryEntities) -> dict[str, object]:
        return {"as_of_date": entities.as_of_date.isoformat()} if entities.as_of_date else {}

    @staticmethod
    def _open_purchase(question: str) -> bool:
        return any(word in question for word in ("未完成", "未结", "开放", "在途"))

    @staticmethod
    def _business_reference(question: str) -> bool:
        if any(word in question for word in (
            "本公司", "本企业", "我们公司", "ChangePilot", "当前库存",
        )):
            return True
        if "当前" in question and any(word in question for word in ("ECR", "ECO", "工程变更")):
            return True
        return any(word in question for word in (
            "它", "其中", "这个产品", "这个零件", "这个供应商", "库存", "BOM",
            "替代料", "替代关系", "订单", "供应哪些", "供应关系", "被哪些产品使用", "Where-Used",
        )) and not any(word in question for word in ("什么是", "通常", "一般", "区别"))

    @classmethod
    def _general_answer_allowed(cls, question: str, entities: QueryEntities) -> bool:
        return not any((
            entities.parts, entities.products, entities.supplier_code,
            entities.purchase_order, entities.production_order, entities.sales_order,
        )) and not cls._business_reference(question)

    @staticmethod
    def _analysis_requested(question: str) -> bool:
        return any(word in question for word in ("分析", "解释", "说明", "比较", "风险", "重要"))

    @classmethod
    def _mixed_analysis_requested(cls, question: str) -> bool:
        return cls._analysis_requested(question) and any(word in question for word in (
            "库存", "采购", "替代料", "BOM", "Where-Used", "被哪些产品使用",
        ))

    @classmethod
    def _missing_requested_facts(cls, question: str, facts: list[ToolFact]) -> bool:
        if not cls._analysis_requested(question):
            return False
        names = {fact.name for fact in facts}
        required = (
            ({"get_inventory"} if "库存" in question else set())
            | ({"get_purchase_orders", "get_purchase_order_records"}
               if "采购" in question else set())
            | ({"get_alternatives"} if "替代料" in question else set())
            | ({"get_bom_structure"} if "BOM" in question.upper() else set())
            | ({"find_where_used"} if any(
                word in question for word in ("Where-Used", "被哪些产品使用")
            ) else set())
        )
        for group in (
            {"get_inventory"}, {"get_purchase_orders", "get_purchase_order_records"},
            {"get_alternatives"}, {"get_bom_structure"}, {"find_where_used"},
        ):
            if required & group and not names & group:
                return True
        return False

    @staticmethod
    def _grounded_analysis(
        analysis: str, facts: list[ToolFact], question: str,
        verified_summaries: str = "",
    ) -> bool:
        """Reject unsupported identifiers and numbers in model-authored prose."""
        import re

        evidence = question + " " + verified_summaries + " " + " ".join(
            json.dumps(fact.data, ensure_ascii=False, default=str) for fact in facts
        )
        codes = re.findall(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", analysis, re.IGNORECASE)
        if any(code.upper() not in evidence.upper() for code in codes):
            return False
        number_pattern = r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])"
        without_codes = re.sub(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", " ", analysis, flags=re.IGNORECASE)
        evidence_without_codes = re.sub(
            r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", " ", evidence,
            flags=re.IGNORECASE,
        )
        numbers = re.findall(number_pattern, without_codes)
        evidence_numbers = {
            Decimal(item) for item in re.findall(number_pattern, evidence_without_codes)
        }
        return all(Decimal(number) in evidence_numbers for number in numbers)

    @staticmethod
    def _data(result: ToolMessage) -> object | None:
        try:
            return json.loads(str(result.content))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _update_context(context: AssistantContext, fact: ToolFact) -> None:
        target = fact.arguments.get("part_number")
        if isinstance(target, str) and fact.name == "get_bom_structure":
            context.current_product = target
            context.current_focus = "product"
        elif isinstance(target, str) and fact.name in _PART_TOOLS:
            context.current_part = target
            context.current_focus = "part"
        revision = fact.arguments.get("revision_code")
        if isinstance(revision, str) and revision:
            context.current_revision = revision
        context.last_intent = fact.name
        context.last_result_type = "alternatives" if fact.name == "get_alternatives" else fact.name
        context.last_result_entities = []
        if fact.name == "get_alternatives" and isinstance(fact.data, dict):
            context.last_result_entities = [
                {"part_number": str(row["alternative_part_number"]),
                 "qualification_status": str(row["qualification_status"])}
                for row in fact.data.get("rows", [])[:50]
                if isinstance(row, dict) and row.get("alternative_part_number")
            ]

    @staticmethod
    def _empty_fact(fact: ToolFact) -> bool:
        data = fact.data
        if isinstance(data, list):
            return not data
        if isinstance(data, dict):
            field = {
                "get_bom_structure": "totals", "find_where_used": "products",
            }.get(fact.name, "rows")
            return not data.get(field) if field in data else not data
        return True

    @staticmethod
    def _display_value(key: str, value: object) -> str:
        if value is None:
            return "—"
        if key in {"planned_start", "planned_end", "created_at", "updated_at"}:
            timestamp = datetime.fromisoformat(str(value))
            return shanghai_datetime(timestamp).strftime("%Y-%m-%d %H:%M")
        if key.startswith("qty_") or key.endswith(("qty", "quantity")) or key in {
            "unit_price", "unit_cost", "quality_rating", "delivery_rating",
        }:
            return format(Decimal(str(value)).normalize(), "f")
        return business_value(value).replace("|", "\\|")

    @classmethod
    def _table(cls, rows: list[dict[str, object]], columns: tuple[str, ...]) -> str:
        headings = " | ".join(_DISPLAY_NAMES.get(key, key) for key in columns)
        divider = " | ".join("---" for _ in columns)
        lines = ["| " + headings + " |", "| " + divider + " |"]
        for row in rows[:100]:
            lines.append("| " + " | ".join(cls._display_value(key, row.get(key)) for key in columns) + " |")
        if len(rows) > 100:
            lines.append(f"\n仅显示前 100 条，共 {len(rows)} 条。")
        return "\n".join(lines)

    @classmethod
    def _format_fact(cls, fact: ToolFact, question: str = "") -> str:
        data = fact.data
        target = str(fact.arguments.get("part_number", ""))
        if fact.name == "get_bom_structure" and isinstance(data, dict):
            totals = data.get("totals")
            if not isinstance(totals, dict) or not totals:
                return f"{target} 在指定业务日期暂无有效 BOM 零件明细。"
            requested = extract_entities(question).parts if "其中" in question else ()
            selected = {key: value for key, value in totals.items()
                        if not requested or key.split("|", 1)[0] in requested}
            if not selected:
                return f"{target} 的有效 BOM 中没有 {requested[0]}。"
            lines = [{"part_number": key.split("|", 1)[0],
                      "revision_code": key.split("|", 1)[1] if "|" in key else "—",
                      "required_qty": value} for key, value in selected.items()]
            return f"{target} 在 {data.get('as_of_date')} 的有效 BOM（每件产品用量）：\n\n" + cls._table(
                lines, ("part_number", "revision_code", "required_qty"),
            )
        if fact.name == "find_where_used" and isinstance(data, dict):
            products = data.get("products", [])
            return (f"当前有效产品结构中，{target} 被以下产品使用：" + "、".join(map(str, products)) + "。"
                    if products else f"当前有效产品结构中，暂无产品使用 {target}。")
        if fact.name == "get_inventory" and isinstance(data, dict):
            rows = data.get("rows", [])
            if not rows:
                return f"未查询到 {target} 的库存记录。"
            on_hand = sum(Decimal(str(row["qty_on_hand"])) for row in rows)
            reserved = sum(Decimal(str(row["qty_reserved"])) for row in rows)
            return (f"{target} 当前库存：现有量 {cls._display_value('qty_on_hand', on_hand)}，"
                    f"已预留 {cls._display_value('qty_reserved', reserved)}，"
                    f"可用量 {cls._display_value('qty_on_hand', on_hand - reserved)}；"
                    f"共 {len(rows)} 条库存记录。")
        if fact.name == "get_alternatives" and isinstance(data, dict):
            rows = data.get("rows", [])
            qualification = "UNQUALIFIED" if "未认证" in question else "QUALIFIED" if "已认证" in question else None
            if qualification:
                rows = [row for row in rows if row.get("qualification_status") == qualification]
            if not rows:
                return f"暂无 {target} 的{'未认证' if qualification == 'UNQUALIFIED' else '已认证' if qualification else ''}替代料记录。"
            label = "未认证" if qualification == "UNQUALIFIED" else "已认证" if qualification else ""
            return f"{target} 的{label}替代料：\n\n" + cls._table(
                rows, ("alternative_part_number", "alternative_revision_code", "qualification_status"),
            )
        if fact.name == "get_purchase_orders" and isinstance(data, dict):
            rows = data.get("rows", [])
            if not rows:
                return f"暂无 {target} 的{'未完成' if fact.arguments.get('open_only') else ''}采购订单。"
            return f"{target} 的{'未完成' if fact.arguments.get('open_only') else ''}采购订单：\n\n" + cls._table(
                rows, ("po_number", "po_status", "supplier_name", "ordered_qty", "received_qty"),
            )
        if isinstance(data, list):
            if not data:
                return "查询成功，暂无符合条件的业务记录。"
            rows = [row for row in data if isinstance(row, dict)]
            columns = {
                "get_suppliers": ("supplier_code", "supplier_name", "status"),
                "get_supplier_parts": ("supplier_code", "supplier_name", "part_number", "revision_code", "qualification_status", "status"),
                "get_purchase_order_records": ("order_number", "supplier_code", "status", "expected_date"),
                "get_production_order_records": ("order_number", "product_part_number", "status", "planned_qty", "planned_start"),
                "get_sales_order_records": ("order_number", "customer_code", "status", "order_date"),
                "get_production_orders_for_part": ("order_number", "part_number", "required_qty"),
            }.get(fact.name)
            if not columns:
                columns = tuple(rows[0].keys())[:8]
            return f"查询到 {len(rows)} 条业务记录：\n\n" + cls._table(rows, columns)
        if isinstance(data, dict):
            header = [f"- {_DISPLAY_NAMES.get(key, key)}：{cls._display_value(key, value)}"
                      for key, value in data.items() if not isinstance(value, (dict, list))]
            sections = ["查询到的业务详情：", *header]
            for key, value in data.items():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    sections.append(f"\n{key}：\n\n" + cls._table(value, tuple(value[0].keys())[:8]))
            return "\n".join(sections)
        return "业务查询返回的结果格式不正确，请稍后重试。"

    @staticmethod
    def _format_multi_agent(result: MultiAgentResult) -> str:
        sections: list[str] = ["### 企业事实"]
        if result.status == "PARTIAL":
            sections.insert(0, "**部分领域查询失败，本次结论基于已成功核验的数据。**")
        for domain in result.domains:
            if domain.facts:
                sections.extend(f"- {item}" for item in domain.facts)
        if len(sections) == 1:
            sections.append("暂无经核验的企业事实。")
        risks = [risk for domain in result.domains for risk in domain.risks]
        sections.append("### 风险判断\n\n" + "\n".join(
            f"- {item}" for item in [*risks, result.judgment] if item
        ))
        unknowns = [item for domain in result.domains for item in domain.unknowns]
        if unknowns:
            sections.append("### 不确定项\n\n" + "\n".join(f"- {item}" for item in unknowns))
        recommendations = [*result.recommendations]
        if recommendations:
            sections.append("### 建议动作\n\n" + "\n".join(
                f"- {item}" for item in recommendations
            ))
        return "\n\n".join(sections)
