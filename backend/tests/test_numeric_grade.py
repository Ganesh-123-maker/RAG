"""Specific-number grade bar (2026-10-27, un-16 diagnosis).

un-16 asks for the exact recall of HNSW at 100 million vectors.
The live run answered with the guide's 12-million figure plus an
explicit disclaimer that the 100-million figure is not provided --
so no answer-side check can catch it: the answer's numbers (12
million, 0.97) ARE in its cited chunk. The leak is question-side:
the asked scale (100 million) is absent from the evidence, and
lexical coverage cannot see it either, because "million" matches
the 12-million chunk. So the grade -- not verify -- carries this
bar: a specific question number missing from the retrieved chunks
grades poor, and after the single rewrite the graph refuses.

Measured on the eval set: no golden question carries a specific
number (>= 1000 after magnitude expansion), so this bar touches no
golden; it touches exactly un-08 (2024) and un-16 (100 million).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_service import (
    REFUSAL_TEXT,
    AgentService,
    _agent_graph,
    _canonical_numbers,
    grade_retrieval_node,
    missing_specific_numbers,
)
from app.services.vector_store_service import RetrievedChunk

CHUNK_12M = (
    "A worked example in this guide indexes 12 million product vectors and "
    "measures recall of 0.97, meaning 97 out of 100 true nearest neighbours "
    "are found. HNSW search builds a layered graph for vector search."
)


def _chunk(chunk_id: str, text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        text=text,
        document_id=str(uuid.uuid4()),
        document_name="facts.txt",
        chunk_index=0,
        score=score,
        chunk_id=chunk_id,
    )


def _as_dicts(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "text": c.text,
            "document_id": c.document_id,
            "document_name": c.document_name,
            "chunk_index": c.chunk_index,
            "score": c.score,
            "chunk_id": c.chunk_id,
            "page": c.page,
            "section": c.section,
        }
        for c in chunks
    ]


def test_canonical_numbers_expand_magnitudes_and_percents() -> None:
    assert _canonical_numbers("100 million vectors") == {100_000_000.0}
    assert _canonical_numbers("12,000 items") == {12_000.0}
    assert _canonical_numbers("97% recall") == {97.0, 0.97}
    assert _canonical_numbers("recall of 0.97") == {0.97}
    assert _canonical_numbers("512-token chunks") == {512.0}


def test_un16_scale_is_missing_while_12m_chunk_present() -> None:
    chunks = _as_dicts([_chunk("c-g", CHUNK_12M, 0.95)])
    missing = missing_specific_numbers(
        "What is the exact recall of HNSW at 100 million vectors in the guide?",
        chunks,
    )
    assert missing == [100_000_000.0]


def test_small_question_numbers_are_exempt() -> None:
    chunks = _as_dicts(
        [_chunk("c-g", "Chunking splits text into 512-token chunks.", 0.95)]
    )
    assert (
        missing_specific_numbers(
            "What is the step between chunk starts for 512-token chunks?",
            chunks,
        )
        == []
    )


def test_covered_year_is_not_missing() -> None:
    chunks = _as_dicts(
        [_chunk("c-g", "The 2024 Olympic marathon was held in Paris.", 0.95)]
    )
    assert (
        missing_specific_numbers("Who won the 2024 Olympic men's marathon?", chunks)
        == []
    )


def test_uncovered_year_is_missing() -> None:
    chunks = _as_dicts([_chunk("c-g", "The Olympic marathon is a long race.", 0.95)])
    assert missing_specific_numbers(
        "Who won the 2024 Olympic men's marathon?", chunks
    ) == [2024.0]


def test_large_percent_question_matches_plain_chunk_form() -> None:
    chunks = _as_dicts([_chunk("c-g", "The increase was 15 times.", 0.95)])
    assert missing_specific_numbers("What is the 1500% increase figure?", chunks) == []
    chunks_other = _as_dicts([_chunk("c-g", "The increase was 20 times.", 0.95)])
    assert missing_specific_numbers(
        "What is the 1500% increase figure?", chunks_other
    ) == [1500.0]


@pytest.mark.asyncio
async def test_grade_poor_on_missing_specific_number_despite_good_score() -> None:
    chunks = _as_dicts([_chunk("c-g", CHUNK_12M, 0.95)])
    state = {
        "question": "What is the exact recall of HNSW at 100 million vectors in the guide?",
        "chunks": chunks,
    }
    result = await grade_retrieval_node(state)
    assert result["retrieval_grade"] == "poor"
    assert "100,000,000" in result["grade_reason"]


class _FakeLLM:
    """Planner says retrieve; rewrite returns a new query."""

    def __init__(self) -> None:
        self.reasoning_calls = 0

    async def create(self, *args, **kwargs):
        if kwargs.get("response_format"):
            user = " ".join(
                msg.get("content", "")
                for msg in kwargs.get("messages", [])
                if msg.get("role") == "user"
            )
            if "Previous retrieval query" in user:
                return _resp(
                    '{"needs_retrieval": true, "retrieval_query": "rewritten query"}'
                )
            return _resp(
                '{"needs_retrieval": true, "retrieval_query": "HNSW recall vectors"}'
            )
        self.reasoning_calls += 1
        return _resp("Never shown.")


def _resp(content: str) -> MagicMock:
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    return resp


async def _run_graph(fake: _FakeLLM, searches: list, question: str):
    owner = uuid.uuid4()
    agent = AgentService()
    initial = agent._initial_state(question, owner, [], None)
    with (
        patch(
            "app.services.agent_service.get_openai_client",
            return_value=MagicMock(
                chat=MagicMock(
                    completions=MagicMock(create=AsyncMock(side_effect=fake.create))
                )
            ),
        ),
        patch(
            "app.services.agent_service.EmbeddingService.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 3072,
        ),
        patch(
            "app.services.agent_service.VectorStoreService.search",
            new_callable=AsyncMock,
            side_effect=searches,
        ),
    ):
        return await _agent_graph.ainvoke(initial)


@pytest.mark.asyncio
async def test_un16_shape_refuses_without_reasoning() -> None:
    fake = _FakeLLM()
    chunk = _chunk("c-g", CHUNK_12M, 0.95)
    final = await _run_graph(
        fake,
        [[chunk], [chunk]],
        "What is the exact recall of HNSW at 100 million vectors in the guide?",
    )
    assert final["answer"] == REFUSAL_TEXT
    assert final["citations"] == []
    assert fake.reasoning_calls == 0
