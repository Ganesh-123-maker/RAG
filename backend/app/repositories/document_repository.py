from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


class DocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        owner_id: uuid.UUID,
        filename: str,
        original_name: str,
        file_type: str,
        file_size_bytes: int,
    ) -> Document:
        doc = Document(
            owner_id=owner_id,
            filename=filename,
            original_name=original_name,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            status="processing",
        )
        self._db.add(doc)
        await self._db.flush()
        return doc

    async def get_by_id(self, doc_id: uuid.UUID) -> Document | None:
        result = await self._db.execute(select(Document).where(Document.id == doc_id))
        return result.scalar_one_or_none()

    async def get_by_owner(self, owner_id: uuid.UUID) -> Sequence[Document]:
        result = await self._db.execute(
            select(Document)
            .where(Document.owner_id == owner_id)
            .order_by(Document.created_at.desc())
        )
        return result.scalars().all()

    async def mark_ready(self, doc_id: uuid.UUID, chunk_count: int) -> None:
        doc = await self.get_by_id(doc_id)
        if doc:
            doc.status = "ready"
            doc.chunk_count = chunk_count

    async def mark_error(self, doc_id: uuid.UUID, message: str) -> None:
        doc = await self.get_by_id(doc_id)
        if doc:
            doc.status = "error"
            doc.error_message = message

    async def delete(self, doc_id: uuid.UUID) -> None:
        doc = await self.get_by_id(doc_id)
        if doc:
            await self._db.delete(doc)
