"""SQLAlchemy persistence for independent assistant conversations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.postgres.models.assistant import AssistantConversation, AssistantMessage


class AssistantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_conversation(self, title: str) -> AssistantConversation:
        row = AssistantConversation(
            id=uuid.uuid4(), title=title, status="ACTIVE", context_json={}
        )
        self._session.add(row)
        self._session.flush()
        return row

    def list_conversations(self) -> list[AssistantConversation]:
        return list(self._session.scalars(
            select(AssistantConversation).order_by(AssistantConversation.updated_at.desc())
        ))

    def get_conversation(
        self, conversation_id: uuid.UUID, *, for_update: bool = False
    ) -> AssistantConversation | None:
        query = select(AssistantConversation).where(AssistantConversation.id == conversation_id)
        if for_update:
            query = query.with_for_update()
        return self._session.scalar(query)

    def list_messages(self, conversation_id: uuid.UUID) -> list[AssistantMessage]:
        return list(self._session.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation_id)
            .order_by(AssistantMessage.created_at, AssistantMessage.id)
        ))

    def add_message(
        self, conversation_id: uuid.UUID, role: str, content: str,
        metadata_json: dict[str, object] | None = None,
    ) -> AssistantMessage:
        row = AssistantMessage(
            id=uuid.uuid4(), conversation_id=conversation_id, role=role,
            content=content, metadata_json=metadata_json or {},
            created_at=datetime.now(UTC),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def set_context(
        self, conversation: AssistantConversation, context: dict[str, object]
    ) -> None:
        conversation.context_json = context
        conversation.updated_at = datetime.now(UTC)
        self._session.flush()

    def delete_conversation(self, conversation: AssistantConversation) -> None:
        self._session.execute(delete(AssistantMessage).where(
            AssistantMessage.conversation_id == conversation.id
        ))
        self._session.delete(conversation)
        self._session.flush()
