"""Persistent employee assistant HTTP endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.domain.dto.assistant import AssistantTurnResult, ConversationDetail, ConversationSummary
from app.llm.client import LLMConfigurationError, LLMResponseError
from app.services.assistant import AssistantService

router = APIRouter(prefix="/api/v1/assistant/conversations", tags=["assistant"])
logger = logging.getLogger(__name__)


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="新对话", min_length=1, max_length=200)


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=4000)


def get_assistant_service() -> AssistantService:
    return AssistantService()


Service = Annotated[AssistantService, Depends(get_assistant_service)]


@router.post("", response_model=ConversationSummary, status_code=201)
def create_conversation(request: CreateConversationRequest, service: Service) -> ConversationSummary:
    return service.create(request.title)


@router.get("", response_model=list[ConversationSummary])
def list_conversations(service: Service) -> list[ConversationSummary]:
    return service.list()


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: uuid.UUID, service: Service) -> ConversationDetail:
    try:
        return service.get(conversation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, service: Service) -> None:
    try:
        service.delete(conversation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{conversation_id}/messages", response_model=AssistantTurnResult)
def send_message(
    conversation_id: uuid.UUID, request: SendMessageRequest, service: Service
) -> AssistantTurnResult:
    try:
        return service.send(conversation_id, request.content)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (LLMConfigurationError, LLMResponseError) as exc:
        logger.exception("Enterprise Assistant model call failed")
        raise HTTPException(status_code=503, detail="模型服务暂时不可用，请稍后重试。") from exc
    except RuntimeError as exc:
        logger.exception("Enterprise Assistant request failed")
        raise HTTPException(status_code=502, detail="智能助手暂时无法完成回答，请稍后重试。") from exc
