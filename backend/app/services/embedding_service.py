from __future__ import annotations

from openai import AsyncOpenAI

from app.core.config import get_settings

settings = get_settings()

_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


class EmbeddingService:
    def __init__(self) -> None:
        self._client = get_openai_client()
        self._model = settings.OPENAI_EMBEDDING_MODEL
        self._dimensions = settings.OPENAI_EMBEDDING_DIMENSIONS

    async def embed_text(self, text: str) -> list[float]:
        text = text.replace("\n", " ")
        response = await self._client.embeddings.create(
            input=[text],
            model=self._model,
            dimensions=self._dimensions,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        cleaned = [t.replace("\n", " ") for t in texts]
        response = await self._client.embeddings.create(
            input=cleaned,
            model=self._model,
            dimensions=self._dimensions,
        )
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
