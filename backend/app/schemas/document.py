from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: uuid.UUID
    original_name: str
    file_type: str
    file_size_bytes: int
    chunk_count: int
    status: str
    error_message: str | None
    # Phase E: ingestion queue progress (0..100) and attempt count.
    ingestion_progress: int = 0
    ingestion_attempts: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int
