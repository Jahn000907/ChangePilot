"""Read-only Tool Calling reviewer for Supplier EOL strategy candidates."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from app.domain.dto.review import ReviewResult
from app.llm.client import DeepSeekLLMClient, ToolCallingLLMClient
from app.tools.langchain import get_review_tools

if TYPE_CHECKING:
    from app.services.trace import TraceService
    from app.workflows.state import SupplierEOLWorkflowState


_REVIEW_PROMPT = """根据供应商停产影响事实审查候选策略。检查编造事实、未认证替代料误用、忽略库存/采购/生产/产品结构风险、依据不足与待核验事项。
必要时只调用提供的只读 Tool；不得请求或执行写操作。PASS 仅表示可供人工考虑，不是最终批准。
仅返回以下 JSON，字段名和 decision 枚举保持英文；summary、issues、recommendations 必须使用简体中文，零件号等技术标识可保留英文：
{"decision":"PASS|REVISE","summary":"string","issues":["string"],
"recommendations":["string"]}."""


class ReviewAgent:
    """Review strategies with a bounded LLM -> Tool -> LLM loop."""

    def __init__(
        self,
        llm_client: ToolCallingLLMClient | None = None,
        *,
        tools: list[BaseTool] | None = None,
        max_rounds: int = 5,
        trace_service: TraceService | None = None,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be at least 1")
        self._llm_client = llm_client
        self._tools = tools if tools is not None else get_review_tools()
        self._max_rounds = max_rounds
        self._trace_service = trace_service

    def set_trace_service(self, trace_service: TraceService) -> None:
        """Attach the workflow-scoped trace service during graph composition."""
        self._trace_service = trace_service

    def __call__(
        self,
        state: SupplierEOLWorkflowState | dict[str, object],
    ) -> dict[str, object]:
        """Run bounded fact verification and return a validated review update."""
        from app.workflows.state import SupplierEOLWorkflowState

        workflow_state = SupplierEOLWorkflowState.model_validate(state)
        if workflow_state.impact is None:
            raise ValueError("review requires a completed impact result")
        if not workflow_state.strategies:
            raise ValueError("review requires at least one strategy candidate")

        result = self.review_facts(
            impact=workflow_state.impact.model_dump(mode="json"),
            strategies=[strategy.model_dump(mode="json") for strategy in workflow_state.strategies],
            run_id=workflow_state.run_id,
        )
        return {
            "review_result": result,
            "review_status": "COMPLETED",
            "approval_status": "PENDING" if result.decision == "PASS" else "NOT_STARTED",
            "status": "COMPLETED",
            "error": None,
        }

    def review_facts(
        self, *, impact: dict[str, object], strategies: list[dict[str, object]],
        run_id: uuid.UUID | None, system_prompt: str = _REVIEW_PROMPT,
    ) -> ReviewResult:
        """Shared bounded read-only review for a structured impact."""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=json.dumps(
                    {"impact": impact, "strategies": strategies},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            ),
        ]
        client = self._llm_client or DeepSeekLLMClient()
        tool_map = {tool.name: tool for tool in self._tools}

        for round_index in range(self._max_rounds):
            response = client.invoke_with_tools(
                messages=messages, tools=self._tools if round_index < 2 else [],
            )
            messages.append(response)
            if response.tool_calls:
                messages.extend(
                    self._execute_tool_call(
                        tool_call,
                        tool_map,
                        run_id,
                    )
                    for tool_call in response.tool_calls
                )
                if round_index == 1:
                    messages.append(HumanMessage(content=(
                        "只读 Tool 核验已结束。仅根据成功取得的事实输出最终审查 JSON；"
                        "失败的 Tool 不提供事实依据。"
                    )))
                continue

            try:
                return self._parse_review(self._text_content(response))
            except (ValidationError, ValueError) as exc:
                if round_index == self._max_rounds - 1:
                    raise RuntimeError("模型审查结果格式不正确，请稍后重试。") from exc
                messages.append(HumanMessage(content=(
                    "上一条不是有效的审查 JSON。请只返回一个 JSON 对象，字段为 "
                    "decision、summary、issues、recommendations；不要解释或使用 Markdown。"
                )))
                continue

        raise RuntimeError(f"review Tool Calling exceeded {self._max_rounds} LLM rounds")

    def _execute_tool_call(
        self,
        tool_call: dict[str, object],
        tool_map: dict[str, BaseTool],
        run_id: uuid.UUID | None,
    ) -> ToolMessage:
        """Execute one allowed Tool Call and preserve its call id."""
        name = str(tool_call["name"])
        arguments = tool_call.get("args")
        trace_handle = None
        if self._trace_service is not None and run_id is not None:
            trace_handle = self._trace_service.start_tool_call(
                run_id=run_id,
                tool_name=name,
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        tool = tool_map.get(name)
        if tool is None:
            if self._trace_service is not None:
                self._trace_service.finish_tool_call(
                    trace_handle,
                    status="BLOCKED",
                    result_summary={"error": f"unknown read-only Tool: {name}"},
                )
            return ToolMessage(
                content=json.dumps({"error": f"unknown read-only Tool: {name}"}),
                tool_call_id=str(tool_call["id"]),
                name=name,
                status="error",
            )
        try:
            result = tool.invoke(tool_call)
        except Exception as exc:  # noqa: BLE001 - report read-only Tool failure to the model
            if self._trace_service is not None:
                self._trace_service.finish_tool_call(
                    trace_handle,
                    status="FAILED",
                    result_summary={"error": str(exc)[:500]},
                )
            return ToolMessage(
                content=json.dumps({"error": "该项只读查询未取得结果，请勿据此推断事实。"}, ensure_ascii=False),
                tool_call_id=str(tool_call["id"]),
                name=name,
                status="error",
            )
        if not isinstance(result, ToolMessage):
            if self._trace_service is not None:
                self._trace_service.finish_tool_call(
                    trace_handle,
                    status="FAILED",
                    result_summary={"error": "Tool did not return a ToolMessage"},
                )
            raise TypeError(f"LangChain Tool {name} did not return a ToolMessage")
        if self._trace_service is not None:
            content = str(result.content)
            self._trace_service.finish_tool_call(
                trace_handle,
                status="SUCCEEDED",
                result_summary={
                    "content_length": len(content),
                    "content_preview": content[:500],
                },
            )
        return result

    @staticmethod
    def _text_content(message: AIMessage) -> str:
        if not isinstance(message.content, str) or not message.content.strip():
            raise ValueError("review LLM returned no final JSON content")
        return message.content

    @staticmethod
    def _parse_review(content: str) -> ReviewResult:
        try:
            return ReviewResult.model_validate_json(content)
        except ValidationError:
            # Some providers prepend a short explanation despite JSON instructions.
            decoder = json.JSONDecoder()
            for index, character in enumerate(content):
                if character != "{":
                    continue
                try:
                    payload, _ = decoder.raw_decode(content[index:])
                    return ReviewResult.model_validate(payload)
                except (json.JSONDecodeError, ValidationError, ValueError):
                    continue
            raise ValueError("review LLM did not return a valid JSON object") from None
