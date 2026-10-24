from __future__ import annotations

"""Shared RAG answer/citation types.

Phase A note: the old ``RagService.answer()`` duplicate retrieval path was
deleted. There is exactly one RAG orchestration path now, in
``app.services.agent_service`` (LangGraph). This module keeps only what the
agent still needs: the ``RagAnswer`` value type and the ``CITATIONS:``
parser, so citation semantics are identical for the streaming and
non-streaming endpoints.

Phase B note: citations are validated by chunk *id*, not by position.
The model is instructed to cite the ``id`` shown in each ``<context>``
block. The parser looks that id up among the chunks that were actually
retrieved; an unknown id is dropped, never substituted with a different
chunk. This closes the Phase A positional-substitution hole, where a
model's ``[2]`` could silently be rewritten to whatever chunk happened
to be second in retrieval order.
"""

import re
from dataclasses import dataclass

from app.services.vector_store_service import RetrievedChunk


@dataclass
class RagAnswer:
    answer: str
    citations: list[dict]


def parse_citations(raw: str, chunks: list[RetrievedChunk]) -> tuple[str, list[dict]]:
    """Parse a ``CITATIONS:`` block, validating ids against retrieval.

    Accepted line format (from the Phase B prompt)::

        [chunk-id] document_name, chunk N

    Only the bracketed id is trusted, and only as a lookup key: if it
    matches a retrieved chunk's ``chunk_id`` (or its ``document_id`` /
    ``chunk_index`` fallback id), that real chunk is cited. Unknown ids,
    malformed lines, and the old positional format (``[1]`` with no
    matching chunk id) are dropped. Duplicate ids are deduplicated.
    If there is no ``CITATIONS:`` block, the answer is returned with no
    citations rather than invented ones.
    """
    if "CITATIONS:" in raw:
        answer_part, citation_part = raw.split("CITATIONS:", 1)
    else:
        return raw.strip(), []

    answer_text = answer_part.strip()
    by_id = {c.chunk_id: c for c in chunks}
    citations: list[dict] = []
    seen: set[str] = set()

    for line in citation_part.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"\[([^\]]+)\]\s+(.+?),\s+chunk\s+(\d+)", line)
        if not m:
            continue
        cited_id = m.group(1).strip()
        chunk = by_id.get(cited_id)
        if chunk is None or chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        citations.append(
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "document_name": chunk.document_name,
                "chunk_index": chunk.chunk_index,
                "page": chunk.page,
                "section": chunk.section,
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
