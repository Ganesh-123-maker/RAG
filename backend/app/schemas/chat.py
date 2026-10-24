from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class CitationSchema(BaseModel):
    document_id: str
    document_name: str
    chunk_index: int
    score: float
    snippet: str
    # Phase B: stable chunk id, page and section when known. Defaults
    # keep citations stored before Phase B (without these fields) valid.
    chunk_id: str = ""
    page: int | None = None
    section: str | None = None


class ChatRequest(BaseModel):
    question: str
    conversation_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[CitationSchema]
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    messages: list[MessageResponse] = []

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]
