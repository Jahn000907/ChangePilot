"""Conversation application service: persistence, context and grounded response."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agents.assistant_queries import extract_entities, substitution_pair
from app.agents.enterprise_assistant import EnterpriseAssistant, ToolFact
from app.agents.supervisor import SupervisorPlanningError
from app.db.postgres.repositories.assistant import AssistantRepository
from app.db.postgres.session import create_session
from app.domain.dto.assistant import (
    AssistantContext,
    AssistantTurnResult,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    WorkflowSuggestion,
)
from app.llm.client import LLMResponseError
from app.services.trace import TraceService


class AssistantService:
    def __init__(
        self, session_factory: Callable[[], Session] | None = None,
        assistant: EnterpriseAssistant | None = None,
        trace_service: TraceService | None = None,
    ) -> None:
        self._sessions = session_factory or create_session
        self._trace = trace_service or TraceService(session_factory=self._sessions)
        self._assistant = assistant or EnterpriseAssistant(trace_service=self._trace)

    def create(self, title: str = "新对话") -> ConversationSummary:
        with self._sessions() as session:
            row = AssistantRepository(session).create_conversation(title.strip() or "新对话")
            session.commit()
            return self._summary(row)

    def list(self) -> list[ConversationSummary]:
        with self._sessions() as session:
            return [self._summary(row) for row in AssistantRepository(session).list_conversations()]

    def get(self, conversation_id: uuid.UUID) -> ConversationDetail:
        with self._sessions() as session:
            repo = AssistantRepository(session)
            row = repo.get_conversation(conversation_id)
            if row is None:
                raise LookupError("对话不存在")
            return ConversationDetail(
                **self._summary(row).model_dump(),
                messages=[self._message(item) for item in repo.list_messages(conversation_id)],
            )

    def delete(self, conversation_id: uuid.UUID) -> None:
        with self._sessions() as session:
            repo = AssistantRepository(session)
            row = repo.get_conversation(conversation_id, for_update=True)
            if row is None:
                raise LookupError("对话不存在")
            repo.delete_conversation(row)
            session.commit()

    def send(self, conversation_id: uuid.UUID, content: str) -> AssistantTurnResult:
        question = content.strip()
        if not question:
            raise ValueError("消息不能为空")
        # Load one conversation only; no process-local memory is shared between sessions.
        with self._sessions() as session:
            repo = AssistantRepository(session)
            row = repo.get_conversation(conversation_id, for_update=True)
            if row is None:
                raise LookupError("对话不存在")
            if row.status != "ACTIVE":
                raise ValueError("该对话已归档")
            history = [(item.role, item.content) for item in repo.list_messages(conversation_id)]
            context = self._extract_context(question, AssistantContext.model_validate(row.context_json))
            facts: list[ToolFact] = []
            failed = False
            answer_status = "SUCCESS"
            if self._ambiguous_reference(question, context):
                answer, tools = "请说明“它”或“其中”具体指哪个产品或零件。", []
                answer_status = "MISSING_INPUT"
            else:
                run_id = uuid.uuid4()
                self._trace.create_run(run_id, workflow_name="enterprise_assistant")
                step_id, clock = self._trace.start_step(
                    run_id=run_id, node_name="assistant_response",
                    agent_name="EnterpriseAssistant", input_summary={"conversation_id": str(conversation_id)},
                )
                try:
                    with self._trace.bind_step(step_id):
                        outcome = self._assistant.answer(
                            question, context, history, run_id
                        )
                        answer, tools, context = outcome.text, outcome.tool_names, outcome.context
                        facts, failed = outcome.facts, outcome.failed
                        answer_status = outcome.status
                except Exception as exc:
                    code = (
                        "SUPERVISOR_PLAN_RETRY_FAILED" if isinstance(exc, SupervisorPlanningError)
                        else "LLM_TIMEOUT" if isinstance(exc, LLMResponseError)
                        else "DOMAIN_AGENT_FAILED"
                    )
                    self._trace.finish_step(step_id=step_id, started_clock=clock,
                                            status="FAILED", error=code)
                    self._trace.update_run_status(run_id, "FAILED", error=code)
                    raise
                self._trace.finish_step(step_id=step_id, started_clock=clock,
                                        status="SUCCEEDED", output_summary={
                                            "tool_names": tools, "answer_status": answer_status,
                                        })
                self._trace.update_run_status(run_id, "SUCCEEDED")
            repo.add_message(conversation_id, "user", question)
            saved = repo.add_message(conversation_id, "assistant", answer,
                                     {"tool_names": tools, "answer_status": answer_status})
            if not history and row.title == "新对话":
                row.title = question[:80]
            repo.set_context(row, context.model_dump(exclude_none=True))
            session.commit()
            return AssistantTurnResult(
                conversation_id=conversation_id, assistant_message=self._message(saved),
                context=context, workflow_suggestion=self._suggest(question, context, facts, failed),
                answer_status=answer_status,
            )

    @staticmethod
    def _extract_context(question: str, context: AssistantContext) -> AssistantContext:
        result = context.model_copy(deep=True)
        mentioned_subjects: set[str] = set()
        entities = extract_entities(question)
        if entities.supplier_name:
            result.current_supplier_name = entities.supplier_name
            result.current_focus = "supplier"
        for value in (*entities.products, *entities.parts, *filter(None, (
            entities.supplier_code, entities.purchase_order,
            entities.production_order, entities.sales_order,
        ))):
            prefix = value.split("-", 1)[0]
            if value in entities.products:
                key, focus = "current_product", "product"
            elif value in entities.parts:
                key, focus = "current_part", "part"
            else:
                special = {
                    "SUP": ("current_supplier_code", "supplier"),
                    "PO": ("current_purchase_order", "purchase_order"),
                    "MO": ("current_production_order", "production_order"),
                    "SO": ("current_sales_order", "sales_order"),
                }
                if prefix not in special:
                    continue
                key, focus = special[prefix]
            same_subject = getattr(result, key) == value and result.current_focus == focus
            setattr(result, key, value)
            result.current_focus = focus
            if focus in {"product", "part"}:
                mentioned_subjects.add(value)
                if not same_subject:
                    result.current_revision = None
        if len(mentioned_subjects) > 1:
            result.current_focus = None
            result.current_revision = None
        if entities.revision:
            result.current_revision = entities.revision
        return result

    @staticmethod
    def _ambiguous_reference(question: str, context: AssistantContext) -> bool:
        if "其中" in question and not (context.current_product or context.last_result_entities):
            return True
        if not any(word in question for word in ("它", "该零件", "这个零件", "这个产品", "这个供应商")):
            return False
        entities = extract_entities(question)
        if entities.parts or entities.products or entities.supplier_code:
            return False
        if "这个产品" in question:
            return context.current_product is None
        if "这个供应商" in question:
            return context.current_focus != "supplier" or not (
                context.current_supplier_code or context.current_supplier_name
            )
        if "这个零件" in question or any(
            word in question for word in ("替代料", "替代关系", "库存", "被哪些产品使用")
        ):
            return context.current_focus != "part"
        return context.current_focus is None

    @staticmethod
    def _suggest(
        question: str, context: AssistantContext, facts: list[ToolFact], failed: bool,
    ) -> WorkflowSuggestion | None:
        entities = extract_entities(question)
        known_part = entities.parts[0] if len(entities.parts) == 1 else context.current_part
        if (known_part and context.current_revision
                and any(word in question.upper() for word in ("停产", "EOL", "断供", "LAST TIME BUY"))
                and any(fact.name in {"get_supplier_parts", "find_where_used",
                                          "get_production_requirements"}
                        and isinstance(fact.data, (list, dict))
                        and (fact.data if isinstance(fact.data, list) else
                             fact.data.get("products") or fact.data.get("rows"))
                        and fact.arguments.get("part_number") == known_part
                        for fact in facts)):
            return WorkflowSuggestion(
                workflow="supplier_eol", label="发起供应商停产分析",
                prefill={k: v for k, v in {
                    "part_number": known_part,
                    "revision": context.current_revision,
                    "supplier_code": context.current_supplier_code,
                }.items() if v},
            )
        pair = substitution_pair(question)
        if (not failed and pair and any(word in question for word in ("评估", "替代", "替换"))
                and any(fact.name == "get_alternatives" and isinstance(fact.data, dict)
                        and any(row.get("alternative_part_number") == pair[1]
                                for row in fact.data.get("rows", []))
                        for fact in facts)):
            return WorkflowSuggestion(
                workflow="material_substitution", label="发起物料替代评估",
                prefill={k: v for k, v in {
                    "part_number": pair[0],
                    "revision": context.current_revision,
                    "candidate_part_number": pair[1],
                }.items() if v},
            )
        return None

    @staticmethod
    def _summary(row: object) -> ConversationSummary:
        return ConversationSummary.model_validate({
            "id": row.id, "title": row.title, "status": row.status,
            "context": AssistantContext.model_validate(row.context_json),
            "created_at": row.created_at, "updated_at": row.updated_at,
        })

    @staticmethod
    def _message(row: object) -> ConversationMessage:
        return ConversationMessage.model_validate({
            "id": row.id, "conversation_id": row.conversation_id,
            "role": row.role, "content": row.content,
            "metadata_json": row.metadata_json, "created_at": row.created_at,
        })
