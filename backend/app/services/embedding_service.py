from __future__ import annotations

import hashlib
import logging
from openai import AsyncOpenAI

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _generate_fallback_embedding(text: str, dim: int = 3072) -> list[float]:
    seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
    vec = []
    for i in range(dim):
        byte_val = seed_bytes[(i % len(seed_bytes))]
        val = ((byte_val ^ (i & 0xFF)) / 255.0) - 0.5
        vec.append(val)
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / norm for x in vec]


class EmbeddingService:
    def __init__(self) -> None:
        self._client = get_openai_client()
        self._model = settings.OPENAI_EMBEDDING_MODEL
        self._dimensions = settings.OPENAI_EMBEDDING_DIMENSIONS

    async def embed_text(self, text: str) -> list[float]:
        text = text.replace("\n", " ")
        try:
            response = await self._client.embeddings.create(
                input=[text],
                model=self._model,
                dimensions=self._dimensions,
            )
            return response.data[0].embedding
        except Exception as exc:
            logger.warning("OpenAI embedding API call failed (%s); using fallback embedding", exc)
            return _generate_fallback_embedding(text, self._dimensions)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        cleaned = [t.replace("\n", " ") for t in texts]
        try:
            response = await self._client.embeddings.create(
                input=cleaned,
                model=self._model,
                dimensions=self._dimensions,
            )
            return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
        except Exception as exc:
            logger.warning("OpenAI batch embedding API call failed (%s); using fallback embeddings", exc)
            return [_generate_fallback_embedding(t, self._dimensions) for t in cleaned]

