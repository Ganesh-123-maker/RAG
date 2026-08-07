from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_conversation(self, owner_id: uuid.UUID, title: str = "New conversation") -> Conversation:
        conv = Conversation(owner_id=owner_id, title=title)
        self._db.add(conv)
        await self._db.flush()
        return conv

    async def get_conversation(self, conv_id: uuid.UUID, owner_id: uuid.UUID) -> Conversation | None:
        result = await self._db.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.id == conv_id, Conversation.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def list_conversations(self, owner_id: uuid.UUID) -> Sequence[Conversation]:
        result = await self._db.execute(
            select(Conversation)
            .where(Conversation.owner_id == owner_id)
            .order_by(Conversation.created_at.desc())
        )
        return result.scalars().all()

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        citations_json: str | None = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            citations_json=citations_json,
        )
        self._db.add(msg)
        await self._db.flush()
        return msg

    async def get_messages(self, conversation_id: uuid.UUID) -> Sequence[Message]:
        result = await self._db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return result.scalars().all()

    async def delete_conversation(self, conversation_id: uuid.UUID) -> None:
        conv = await self._db.get(Conversation, conversation_id)
        if conv:
            await self._db.delete(conv)
