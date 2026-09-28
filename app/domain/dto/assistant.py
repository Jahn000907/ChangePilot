"""Stable contracts for the persistent employee assistant."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssistantContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_product: str | None = None
    current_part: str | None = None
    current_revision: str | None = None
    current_supplier_code: str | None = None
    current_purchase_order: str | None = None
    current_production_order: str | None = None
    current_sales_order: str | None = None
    current_focus: Literal["product", "part", "supplier", "purchase_order", "production_order", "sales_order"] | None = None


class ConversationMessage(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    metadata_json: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: Literal["ACTIVE", "ARCHIVED"]
    context: AssistantContext
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessage]


class WorkflowSuggestion(BaseModel):
    workflow: Literal["supplier_eol", "material_substitution"]
    label: str
    prefill: dict[str, str]


class AssistantTurnResult(BaseModel):
    conversation_id: uuid.UUID
    assistant_message: ConversationMessage
    context: AssistantContext
    workflow_suggestion: WorkflowSuggestion | None = None
    answer_status: Literal["SUCCESS", "NO_DATA", "MISSING_INPUT", "TOOL_ERROR", "LLM_ERROR"] = "SUCCESS"
