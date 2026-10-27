"""Direct-branch guard (2026-10-27 live re-run diagnosis).

The planner LLM routed all 5 still-answered probes to the direct
branch despite a prompt saying false is for greetings only, so a
direct answer bypassed retrieval, grading, and refusal entirely.
The guard below, not the planner's JSON, decides what may go
direct. These tests pin it at unit and graph level.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_service import (
    REFUSAL_TEXT,
    AgentService,
    _agent_graph,
    is_conversational,
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
    """Planner always says direct; rewrite returns a new query. The
    guard, not the planner, must force factual questions to
    retrieval."""

    def __init__(self, reasoning_answers: list[str]) -> None:
        self.reasoning_answers = reasoning_answers
        self.reasoning_calls = 0
        self.direct_calls = 0

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
            return _resp('{"needs_retrieval": false, "retrieval_query": ""}')
        systems = " ".join(
            msg.get("content", "")
            for msg in kwargs.get("messages", [])
            if msg.get("role") == "system"
        )
        if "does not require the user's documents" in systems:
            self.direct_calls += 1
        else:
            self.reasoning_calls += 1
        return _resp(self.reasoning_answers[0])


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


# --- guard unit tests ---


@pytest.mark.parametrize(
    "question",
    [
        "Hello",
        "Hi there!",
        "Good morning",
        "Thanks!",
        "Thank you so much",
        "Bye",
        "How are you?",
        "How are you doing today?",
        "How's it going?",
        "What's up?",
        "What can you do?",
        "Who are you?",
        "Help",
        "OK",
        "",
    ],
)
def test_conversational_messages_stay_direct(question: str) -> None:
    assert is_conversational(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "What is the capital city of France and what is its population?",
        "Explain quantum entanglement in detail.",
        "What is the current stock price of Tesla?",
        "What is the weather forecast for London tomorrow?",
        "What are the lyrics to the song Bohemian Rhapsody?",
        "How does HNSW search work in a vector database?",
        "What is the Qdrant replication factor for a cluster in Antarctica?",
    ],
)
def test_factual_questions_are_not_conversational(question: str) -> None:
    assert is_conversational(question) is False


def test_greeting_prefix_needs_word_boundary() -> None:
    # "history" starts with "hi" but is not a greeting.
    assert is_conversational("History of the Roman Empire") is False


# --- graph tests: planner says direct, guard decides ---


@pytest.mark.asyncio
async def test_factual_direct_plan_is_forced_to_retrieval_and_refused() -> None:
    fake = _FakeLLM(["Never shown."])
    disjoint = [_chunk("c-x", "HNSW builds a layered graph for vector search.", 0.95)]
    final = await _run_graph(
        fake, [disjoint, disjoint], "What is the capital city of France?"
    )
    assert final["answer"] == REFUSAL_TEXT
    assert final["citations"] == []
    assert fake.direct_calls == 0
    assert fake.reasoning_calls == 0


@pytest.mark.asyncio
async def test_factual_direct_plan_with_good_chunks_still_reasons() -> None:
    fake = _FakeLLM(
        ["Paris is the capital of France.\n\nCITATIONS:\n[c-g] facts.txt, chunk 0"]
    )
    good = [_chunk("c-g", "Paris is the capital of France.", 0.95)]
    final = await _run_graph(fake, [good], "What is the capital of France?")
    assert fake.direct_calls == 0
    assert fake.reasoning_calls == 1
    assert final["answer"] != REFUSAL_TEXT


@pytest.mark.asyncio
async def test_greeting_direct_plan_still_answers_directly() -> None:
    fake = _FakeLLM(["Hello! How can I help?"])
    final = await _run_graph(fake, [], "Hello!")
    assert final["answer"] == "Hello! How can I help?"
    assert final["citations"] == []
    assert fake.direct_calls == 1
    assert fake.reasoning_calls == 0
