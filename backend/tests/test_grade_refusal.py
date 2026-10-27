"""Grade-based refusal (2026-10-26): the graph must refuse, without
an LLM call, when retrieval is still poor after the single rewrite.

Measured basis (real Gemini retrieval, chunk level, eval corpus):
golden coverage min 0.67 / median 1.00; the 5 probes the live run
answered all 0.00; threshold 0.50 sits in that gap. These tests pin
the mechanism at unit and graph level; they do NOT claim a new live
refusal rate (that needs a live eval re-run, recorded as pending).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_service import (
    REFUSAL_TEXT,
    AgentService,
    _agent_graph,
    chunk_coverage,
    grade_retrieval_node,
)
from app.services.vector_store_service import RetrievedChunk


def _chunk(chunk_id: str, text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        text=text,
        document_id=str(uuid.uuid4()),
        document_name="facts.txt",
        chunk_index=0,
        score=score,
        chunk_id=chunk_id,
    )


def _resp(content: str) -> MagicMock:
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    return resp


class _FakeLLM:
    """Planner says retrieve, rewrite returns a new query. The
    reasoning answer is grounded in the good chunk, so the good-grade
    test passes verification; the refuse test never reaches reasoning
    at all, which is the point."""

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
                '{"needs_retrieval": true, "retrieval_query": "sourdough bread starter"}'
            )
        self.reasoning_calls += 1
        return _resp(
            "Paris is the capital of France.\n\nCITATIONS:\n[c-g] facts.txt, chunk 0"
        )


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
        # Await INSIDE the patch context: returning the coroutine would
        # run the graph after the mocks are removed.
        return await _agent_graph.ainvoke(initial)


# --- coverage helper ---


def test_coverage_shared_vocabulary_is_high() -> None:
    cov = chunk_coverage(
        "How does HNSW search work in a vector database?",
        [{"text": "HNSW builds a layered graph for vector search."}],
    )
    assert cov >= 0.5


def test_coverage_disjoint_vocabulary_is_zero() -> None:
    cov = chunk_coverage(
        "What is the capital city of France and what is its population?",
        [{"text": "HNSW builds a layered graph for vector search."}],
    )
    assert cov == 0.0


def test_coverage_plural_and_gerund_folding() -> None:
    # "layers" and "layering" both normalize to "layer".
    cov = chunk_coverage(
        "How do layers work?",
        [{"text": "The layering work of the graph is described here."}],
    )
    assert cov == 1.0


def test_coverage_content_free_question_grades_zero() -> None:
    assert chunk_coverage("What is it?", [{"text": "Anything at all."}]) == 0.0


def test_coverage_union_across_chunks() -> None:
    cov = chunk_coverage(
        "How does HNSW search work?",
        [{"text": "HNSW search uses graphs."}, {"text": "The work happens in layers."}],
    )
    assert cov == 1.0


# --- grade node branches ---


@pytest.mark.asyncio
async def test_grade_poor_on_high_score_but_zero_coverage() -> None:
    # The measured probe shape: high similarity, no shared vocabulary.
    result = await grade_retrieval_node(  # type: ignore[arg-type]
        {
            "question": "What is the capital city of France?",
            "chunks": [
                {
                    "score": 0.95,
                    "text": "HNSW builds a layered graph for vector search.",
                }
            ],
            "errors": [],
        }
    )
    assert result["retrieval_grade"] == "poor"
    assert "coverage" in result["grade_reason"]


@pytest.mark.asyncio
async def test_grade_poor_on_low_score_despite_good_coverage() -> None:
    result = await grade_retrieval_node(  # type: ignore[arg-type]
        {
            "question": "What is the capital?",
            "chunks": [{"score": 0.35, "text": "Paris is the capital of France."}],
            "errors": [],
        }
    )
    assert result["retrieval_grade"] == "poor"
    assert "top score" in result["grade_reason"]


@pytest.mark.asyncio
async def test_grade_uses_original_question_not_rewritten_query() -> None:
    # After a rewrite, retrieval_query is the rewriter's wording. A
    # probe must not pass by matching its own rewrite.
    result = await grade_retrieval_node(  # type: ignore[arg-type]
        {
            "question": "What is the capital city of France?",
            "retrieval_query": "HNSW layered graph vector search",
            "chunks": [
                {
                    "score": 0.95,
                    "text": "HNSW builds a layered graph for vector search.",
                }
            ],
            "errors": [],
        }
    )
    assert result["retrieval_grade"] == "poor"


# --- graph level: still-poor after rewrite refuses without reasoning ---


@pytest.mark.asyncio
async def test_still_poor_after_rewrite_refuses_without_reasoning() -> None:
    fake = _FakeLLM()
    # Both retrievals return high-scoring but vocabulary-disjoint chunks.
    disjoint = [_chunk("c-x", "HNSW builds a layered graph for vector search.", 0.95)]
    final = await _run_graph(
        fake,
        [disjoint, disjoint],
        question="What is the capital city of France?",
    )
    assert final["answer"] == REFUSAL_TEXT
    assert final["citations"] == []
    assert final["verify_result"] == "skipped"
    assert fake.reasoning_calls == 0


@pytest.mark.asyncio
async def test_good_grade_still_reasons_normally() -> None:
    fake = _FakeLLM()
    good = [_chunk("c-g", "Paris is the capital of France.", 0.95)]
    final = await _run_graph(
        fake,
        [good],
        question="What is the capital of France?",
    )
    assert fake.reasoning_calls == 1
    assert final["answer"] != REFUSAL_TEXT
