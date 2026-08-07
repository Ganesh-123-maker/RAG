from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.embedding_service import get_openai_client
from app.services.vector_store_service import RetrievedChunk, VectorStoreService

settings = get_settings()

SYSTEM_PROMPT = """\
You are a helpful research assistant.
Answer the user's question using ONLY the provided context chunks.
After your answer, list the sources you used in this exact format:

CITATIONS:
[1] <document_name>, chunk <chunk_index>
[2] ...

If the context does not contain enough information to answer, say so honestly.
Do not make up information.
"""


@dataclass
class RagAnswer:
    answer: str
    citations: list[dict]


class RagService:
    def __init__(self) -> None:
        self._embed_svc_class = None
        self._vector_svc = VectorStoreService()
        self._llm: AsyncOpenAI = get_openai_client()

    async def answer(
        self,
        question: str,
        owner_id: uuid.UUID,
        history: list[dict] | None = None,
        document_id: uuid.UUID | None = None,
    ) -> RagAnswer:
        from app.services.embedding_service import EmbeddingService

        embed_svc = EmbeddingService()
        query_vector = await embed_svc.embed_text(question)

        chunks: list[RetrievedChunk] = await self._vector_svc.search(
            query_vector=query_vector,
            owner_id=owner_id,
            document_id=document_id,
        )

        if not chunks:
            return RagAnswer(
                answer="I couldn't find any relevant information in your documents.",
                citations=[],
            )

        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(
                f"[{i}] From '{chunk.document_name}' (chunk {chunk.chunk_index}):\n{chunk.text}"
            )
        context_block = "\n\n---\n\n".join(context_parts)

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({
            "role": "user",
            "content": f"Context:\n{context_block}\n\nQuestion: {question}",
        })

        response = await self._llm.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=messages,
            temperature=0.1,
        )
        raw_answer = response.choices[0].message.content or ""

        answer_text, citations = self._parse_citations(raw_answer, chunks)

        return RagAnswer(answer=answer_text, citations=citations)

    @staticmethod
    def _parse_citations(raw: str, chunks: list[RetrievedChunk]) -> tuple[str, list[dict]]:
        if "CITATIONS:" in raw:
            answer_part, citation_part = raw.split("CITATIONS:", 1)
        else:
            return raw.strip(), []

        answer_text = answer_part.strip()
        citations: list[dict] = []

        for line in citation_part.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"\[(\d+)\]\s+(.+?),\s+chunk\s+(\d+)", line)
            if m:
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(chunks):
                    chunk = chunks[idx]
                    citations.append({
                        "document_id": chunk.document_id,
                        "document_name": chunk.document_name,
                        "chunk_index": chunk.chunk_index,
                        "score": round(chunk.score, 4),
                        "snippet": chunk.text[:200] + "..." if len(chunk.text) > 200 else chunk.text,
                    })

        return answer_text, citations
