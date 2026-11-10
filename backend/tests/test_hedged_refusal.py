"""Hedged-answer normalization (2026-11-10, un-15 diagnosis).

un-15 (Qdrant replication factor for a cluster in Antarctica) was
the last refusal miss: reasoning answered with a hedge -- "there is
no mention of an Antarctic cluster" plus the guide's replication
factor 2 -- instead of refusing. Measured on the latest live run,
no golden answer contains any absence-admission phrase, so verify
normalizes such an answer to the exact refusal text. The reasoning
prompt now asks for the refusal directly; this rule guarantees it.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_service import (
    REFUSAL_TEXT,
    AgentService,
    _admits_absence,
    _agent_graph,
)
from app.services.vector_store_service import RetrievedChunk

UN15_ANSWER = (
    "Based on the provided context, there is no mention of an Antarctic "
    "cluster. The context only mentions that the example cluster in the "
    "guide uses a replication factor of 2.\n\nCITATIONS:\n[c-g] facts.txt, chunk 0"
)


def test_un15_answer_admits_absence() -> None:
    assert _admits_absence(UN15_ANSWER) is True


@pytest.mark.parametrize(
    "answer",
    [
        "Paris is the capital of France.\n\nCITATIONS:\n[c-g] facts.txt, chunk 0",
        (
            "HNSW builds a layered graph where the upper layers contain a few "
            "long-range links.\n\nCITATIONS:\n[c-g] facts.txt, chunk 0"
        ),
        "The healthcheck runs every 30 seconds.\n\nCITATIONS:\n[c-g] facts.txt, chunk 0",
    ],
)
def test_grounded_answers_do_not_admit_absence(answer: str) -> None:
    assert _admits_absence(answer) is False


def _resp(content: str) -> MagicMock:
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    return resp


class _FakeLLM:
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
                '{"needs_retrieval": true, "retrieval_query": "Qdrant replication factor"}'
            )
        self.reasoning_calls += 1
        return _resp(UN15_ANSWER)


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
async def test_hedged_answer_is_normalized_to_refusal() -> None:
    fake = _FakeLLM()
    chunk = RetrievedChunk(
        text="The example cluster in the guide uses a replication factor of 2.",
        document_id=str(uuid.uuid4()),
        document_name="facts.txt",
        chunk_index=0,
        score=0.95,
        chunk_id="c-g",
    )
    final = await _run_graph(
        fake,
        [[chunk]],
        "What is the Qdrant replication factor for a cluster in Antarctica?",
    )
    assert final["answer"] == REFUSAL_TEXT
    assert final["citations"] == []
    assert fake.reasoning_calls == 1
