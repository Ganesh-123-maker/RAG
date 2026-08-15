import asyncio
import logging
import uuid
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import get_settings
from app.services.chunking_service import TextChunk

settings = get_settings()
logger = logging.getLogger(__name__)

_qdrant_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        if settings.QDRANT_HOST in (":memory:", "memory", ":memory") or settings.QDRANT_HOST.startswith("./"):
            _qdrant_client = AsyncQdrantClient(location=":memory:")
        else:
            # Use HTTPS + API key for Qdrant Cloud; plain HTTP for local instances
            kwargs: dict = {
                "host": settings.QDRANT_HOST,
                "port": settings.QDRANT_PORT,
            }
            if settings.QDRANT_API_KEY:
                kwargs["api_key"] = settings.QDRANT_API_KEY
                kwargs["https"] = True
            _qdrant_client = AsyncQdrantClient(**kwargs)
    return _qdrant_client


@dataclass
class RetrievedChunk:
    text: str
    document_id: str
    document_name: str
    chunk_index: int
    score: float


class VectorStoreService:
    def __init__(self) -> None:
        self._client = get_qdrant_client()
        self._collection = settings.QDRANT_COLLECTION
        self._dim = settings.OPENAI_EMBEDDING_DIMENSIONS

    async def ensure_collection(self) -> None:
        try:
            existing = await self._client.get_collections()
            names = [c.name for c in existing.collections]
            if self._collection not in names:
                await self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(
                        size=self._dim,
                        distance=Distance.COSINE,
                    ),
                )
        except Exception as e:
            logger.warning("Vector DB collection check deferred: %s", e)

    async def upsert_chunks(
        self,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
        owner_id: uuid.UUID,
    ) -> None:
        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "text": chunk.text,
                    "document_id": str(chunk.document_id),
                    "document_name": chunk.document_name,
                    "chunk_index": chunk.chunk_index,
                    "owner_id": str(owner_id),
                },
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]
        await self._client.upsert(collection_name=self._collection, points=points)

    async def search(
        self,
        query_vector: list[float],
        owner_id: uuid.UUID,
        top_k: int = settings.RETRIEVAL_TOP_K,
        document_id: uuid.UUID | None = None,
    ) -> list[RetrievedChunk]:
        must_conditions = [
            FieldCondition(key="owner_id", match=MatchValue(value=str(owner_id)))
        ]
        if document_id is not None:
            must_conditions.append(
                FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))
            )

        results = await self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            query_filter=Filter(must=must_conditions),
            limit=top_k,
            with_payload=True,
        )

        retrieved = []
        for r in results:
            payload = r.payload or {}
            retrieved.append(
                RetrievedChunk(
                    text=payload.get("text", ""),
                    document_id=payload.get("document_id", ""),
                    document_name=payload.get("document_name", "Unknown"),
                    chunk_index=payload.get("chunk_index", 0),
                    score=r.score,
                )
            )
        return retrieved

    async def delete_by_document(self, document_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        await self._client.delete(
            collection_name=self._collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(key="document_id", match=MatchValue(value=str(document_id))),
                        FieldCondition(key="owner_id", match=MatchValue(value=str(owner_id))),
                    ]
                )
            ),
        )
