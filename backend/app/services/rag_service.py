from __future__ import annotations

"""Shared RAG answer/citation types.

Phase A note: the old ``RagService.answer()`` duplicate retrieval path was
deleted. There is exactly one RAG orchestration path now, in
``app.services.agent_service`` (LangGraph). This module keeps only what the
agent still needs: the ``RagAnswer`` value type and the ``CITATIONS:``
parser, so citation semantics are identical for the streaming and
non-streaming endpoints.
"""

import re
from dataclasses import dataclass

from app.services.vector_store_service import RetrievedChunk


@dataclass
class RagAnswer:
    answer: str
    citations: list[dict]


def parse_citations(raw: str, chunks: list[RetrievedChunk]) -> tuple[str, list[dict]]:
    """Parse a ``CITATIONS:`` block out of a model answer.

    Only the positional index from each citation line is trusted, and it is
    bounds-checked against the chunks that were actually retrieved: the
    returned citation always describes a real retrieved chunk (its document
    id/name, chunk index, score and snippet), never a document the model
    merely named. Lines that are malformed or out of range are dropped.
    If there is no ``CITATIONS:`` block, the answer is returned with no
    citations rather than invented ones.
    """
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
                citations.append(
                    {
                        "document_id": chunk.document_id,
                        "document_name": chunk.document_name,
                        "chunk_index": chunk.chunk_index,
                        "score": round(chunk.score, 4),
                        "snippet": chunk.text[:200] + "..."
                        if len(chunk.text) > 200
                        else chunk.text,
                    }
                )

    return answer_text, citations


class RagService:
    """Backward-compatible namespace for the citation parser.

    ``RagService.answer()`` no longer exists (deleted in Phase A); use
    ``AgentService``. This class exists only so existing imports of
    ``RagService._parse_citations`` keep working.
    """

    _parse_citations = staticmethod(parse_citations)
