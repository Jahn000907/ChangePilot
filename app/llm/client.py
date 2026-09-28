"""Small OpenAI-compatible client used for DeepSeek JSON generation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Protocol

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from app.core.config import LLMSettings, get_settings
from app.llm.tracing import instrument_openai


class LLMConfigurationError(RuntimeError):
    """Raised when the configured model provider cannot be initialized."""


class LLMResponseError(RuntimeError):
    """Raised when the provider returns no usable response content."""


class LLMClient(Protocol):
    """Provider-independent JSON generation boundary used by agents."""

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        """Return one JSON object as text."""
        ...


class ToolCallingLLMClient(Protocol):
    """Chat boundary supporting LangChain's standard Tool Calling messages."""

    def invoke_with_tools(
        self,
        *,
        messages: Sequence[BaseMessage],
        tools: Sequence[BaseTool],
    ) -> AIMessage:
        """Return either Tool Calls or final assistant content."""
        ...


class DeepSeekLLMClient:
    """Call DeepSeek through its OpenAI-compatible Chat Completions API."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        llm_settings = settings or get_settings().llm
        api_key = (
            llm_settings.deepseek_api_key.get_secret_value()
            if llm_settings.deepseek_api_key is not None
            else ""
        )
        if not api_key.strip():
            raise LLMConfigurationError(
                "缺少 DEEPSEEK_API_KEY，无法调用企业智能助手或策略模型。"
            )

        self._model = llm_settings.deepseek_model
        self._temperature = llm_settings.llm_temperature
        self._client = instrument_openai(OpenAI(
            api_key=api_key,
            base_url=llm_settings.deepseek_base_url.rstrip("/"),
            timeout=llm_settings.llm_timeout_seconds,
            max_retries=llm_settings.llm_max_retries,
        ))

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        """Generate a JSON object using DeepSeek JSON mode."""
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                response_format={"type": "json_object"},
            )
        except (APITimeoutError, APIConnectionError, RateLimitError, APIStatusError) as exc:
            raise LLMResponseError("模型服务暂时不可用或响应超时，请稍后重试。") from exc
        content = completion.choices[0].message.content
        if not content or not content.strip():
            raise LLMResponseError("DeepSeek returned an empty strategy response")
        return content

    def invoke_with_tools(
        self,
        *,
        messages: Sequence[BaseMessage],
        tools: Sequence[BaseTool],
    ) -> AIMessage:
        """Invoke DeepSeek using LangChain Tool schemas and message semantics."""
        try:
            payload: dict[str, object] = {
                "model": self._model,
                "messages": [self._to_openai_message(message) for message in messages],
                "temperature": self._temperature,
            }
            if tools:
                payload["tools"] = [convert_to_openai_tool(tool) for tool in tools]
                payload["tool_choice"] = "auto"
            else:
                payload["response_format"] = {"type": "json_object"}
            completion = self._client.chat.completions.create(**payload)  # type: ignore[arg-type]
        except (APITimeoutError, APIConnectionError, RateLimitError, APIStatusError) as exc:
            raise LLMResponseError("模型服务暂时不可用或响应超时，请稍后重试。") from exc
        message = completion.choices[0].message
        tool_calls: list[dict[str, object]] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise LLMResponseError(
                    f"DeepSeek returned invalid arguments for Tool {call.function.name}"
                ) from exc
            if not isinstance(arguments, dict):
                raise LLMResponseError(
                    f"DeepSeek returned non-object arguments for Tool {call.function.name}"
                )
            tool_calls.append(
                {
                    "name": call.function.name,
                    "args": arguments,
                    "id": call.id,
                    "type": "tool_call",
                }
            )

        content = message.content or ""
        if not content.strip() and not tool_calls:
            raise LLMResponseError("DeepSeek returned neither Tool Calls nor review content")
        return AIMessage(content=content, tool_calls=tool_calls)  # type: ignore[arg-type]

    @staticmethod
    def _to_openai_message(message: BaseMessage) -> dict[str, object]:
        """Translate the small LangChain message subset used by Review Agent."""
        content = (
            message.content
            if isinstance(message.content, str)
            else json.dumps(message.content, ensure_ascii=False)
        )
        if isinstance(message, SystemMessage):
            return {"role": "system", "content": content}
        if isinstance(message, HumanMessage):
            return {"role": "user", "content": content}
        if isinstance(message, ToolMessage):
            return {
                "role": "tool",
                "content": content,
                "tool_call_id": message.tool_call_id,
            }
        if isinstance(message, AIMessage):
            payload: dict[str, object] = {"role": "assistant", "content": content}
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["args"], ensure_ascii=False),
                        },
                    }
                    for call in message.tool_calls
                ]
            return payload
        raise TypeError(f"unsupported LLM message type: {type(message).__name__}")
