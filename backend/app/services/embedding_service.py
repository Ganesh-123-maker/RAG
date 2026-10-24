from __future__ import annotations

import logging

from openai import AsyncOpenAI
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Maximum inputs per OpenAI embeddings request (Phase A cap; see report).
MAX_EMBEDDING_BATCH = 100
# Retries are handled here by tenacity, so the SDK's own retries are disabled
# to avoid double-counting attempts.
OPENAI_TIMEOUT_SECONDS = 30.0

_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=OPENAI_TIMEOUT_SECONDS,
            max_retries=0,
        )
    return _client


class EmbeddingError(Exception):
    """Raised when an embedding request fails after all retries.

    Deliberately raised instead of returning a substitute vector: a
    silently substituted vector would be indexed as if it were real and
    corrupt retrieval for that document. Callers must surface this as a
    user-visible failure and mark the document as errored.
    """


class EmbeddingService:
    def __init__(self) -> None:
        self._client = get_openai_client()
        self._model = settings.OPENAI_EMBEDDING_MODEL
        self._dimensions = settings.OPENAI_EMBEDDING_DIMENSIONS

    async def _create(self, inputs: list[str]) -> list[list[float]]:
        """One embeddings request, retried with exponential backoff."""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                retry=retry_if_exception_type(Exception),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.embeddings.create(
                        input=inputs,
                        model=self._model,
                        dimensions=self._dimensions,
                    )
                    return [
                        item.embedding
                        for item in sorted(response.data, key=lambda x: x.index)
                    ]
        except Exception as exc:
            logger.error("OpenAI embedding API call failed after retries: %s", exc)
            raise EmbeddingError("Embedding service failed; please try again.") from exc
        raise EmbeddingError("Embedding service failed; please try again.")

    async def embed_text(self, text: str) -> list[float]:
        vectors = await self._create([text.replace("\n", " ")])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        cleaned = [t.replace("\n", " ") for t in texts]
        vectors: list[list[float]] = []
        for i in range(0, len(cleaned), MAX_EMBEDDING_BATCH):
            vectors.extend(await self._create(cleaned[i : i + MAX_EMBEDDING_BATCH]))
        return vectors
