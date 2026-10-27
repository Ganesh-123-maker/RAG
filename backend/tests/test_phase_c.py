"""Phase C tests: graded LangGraph with bounded retry + verification.

All LLM / embedding / vector calls are mocked (deterministic fake LLM);
the COMPILED graph (``_agent_graph.ainvoke``) is exercised, not only
individual nodes, so every conditional branch is covered end to end.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_service import (
    AgentError,
    AgentService,
    _agent_graph,
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
    """Dispatches mocked chat completions by prompt shape.

    Planner and rewrite calls both use ``response_format`` (JSON mode);
    they are told apart by the rewrite prompt's
    "Previous retrieval query" marker. Reasoning calls have no
    ``response_format`` and pop answers from ``reasoning_answers`` in
    order, so verify-regeneration tests can script attempt 1 vs 2.
    """

    def __init__(
        self,
        plan: str,
        rewrite: str,
        reasoning_answers: list[str],
        rewrite_raises: bool = False,
    ) -> None:
        self.plan = plan
        self.rewrite = rewrite
        self.reasoning_answers = list(reasoning_answers)
        self.rewrite_raises = rewrite_raises
        self.rewrite_calls = 0
        self.reasoning_calls = 0
        self.direct_calls = 0

    async def create(self, *args, **kwargs):
        if kwargs.get("stream"):
            # Streaming reasoning call: yield the scripted answer as
            # one token (the reasoning node concatenates sink tokens).
            answer = self.reasoning_answers[
                min(self.reasoning_calls, len(self.reasoning_answers) - 1)
            ]
            self.reasoning_calls += 1

            async def gen():
                chunk = MagicMock()
                delta = MagicMock()
                delta.content = answer
                chunk.choices = [MagicMock(delta=delta)]
                yield chunk

            return gen()
        if kwargs.get("response_format"):
            user = ""
            for msg in kwargs.get("messages", []):
                if msg.get("role") == "user":
                    user = msg.get("content", "")
            if "Previous retrieval query" in user:
                self.rewrite_calls += 1
                if self.rewrite_raises:
                    raise RuntimeError("rewrite LLM down")
                return _resp(self.rewrite)
            return _resp(self.plan)
        systems = " ".join(
            msg.get("content", "")
            for msg in kwargs.get("messages", [])
            if msg.get("role") == "system"
        )
        if "does not require the user's documents" in systems:
            self.direct_calls += 1
        else:
            self.reasoning_calls += 1
        idx = min(
            self.reasoning_calls + self.direct_calls - 1,
            len(self.reasoning_answers) - 1,
        )
        return _resp(self.reasoning_answers[idx])


def _mock_client(fake: _FakeLLM) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=fake.create)
    return client


async def _run_graph(
    fake: _FakeLLM, searches: list, question: str = "What is the capital?"
):
    """Run the compiled graph with mocked LLM/embeddings/search."""
    owner = uuid.uuid4()
    agent = AgentService()
    initial = agent._initial_state(question, owner, [], None)
    with (
        patch(
            "app.services.agent_service.get_openai_client",
            return_value=_mock_client(fake),
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


_PLAN_RETRIEVE = '{"needs_retrieval": true, "retrieval_query": "capital of France"}'
_PLAN_DIRECT = '{"needs_retrieval": false, "retrieval_query": ""}'
_REWRITE = '{"needs_retrieval": true, "retrieval_query": "France capital city"}'
_GOOD_CHUNK = lambda: _chunk("c-good", "Paris is the capital of France.", 0.95)
_LOW_CHUNK = lambda: _chunk("c-low", "Paris is the capital of France.", 0.35)
_GOOD_ANSWER = "Paris is the capital.\n\nCITATIONS:\n[c-good] facts.txt, chunk 0"
_LOW_ANSWER = "Paris is the capital.\n\nCITATIONS:\n[c-low] facts.txt, chunk 0"
_BAD_ANSWER = "Zebra stripes are colourful.\n\nCITATIONS:\n[c-good] facts.txt, chunk 0"


@pytest.mark.asyncio
async def test_grade_node_branches() -> None:
    # Grade now requires score AND coverage of the original question,
    # so the cases carry a question and chunk text (see
    # test_grade_refusal.py for the coverage branches).
    base = {"chunks": [], "errors": [], "question": "What is the capital?"}
    poor_empty = await grade_retrieval_node({**base, "chunks": []})  # type: ignore[arg-type]
    assert poor_empty["retrieval_grade"] == "poor"
    poor_low = await grade_retrieval_node(
        {**base, "chunks": [{"score": 0.35, "text": "Paris is the capital of France."}]}  # type: ignore[arg-type]
    )
    assert poor_low["retrieval_grade"] == "poor"
    good = await grade_retrieval_node(
        {**base, "chunks": [{"score": 0.95, "text": "Paris is the capital of France."}]}  # type: ignore[arg-type]
    )
    assert good["retrieval_grade"] == "good"


@pytest.mark.asyncio
async def test_planner_skip_direct_answer() -> None:
    # The fixture question must be conversational: the 2026-10-27
    # direct-branch guard forces factual questions to retrieval even
    # when the planner says direct, so the old "What is the capital?"
    # fixture would no longer take the direct branch.
    fake = _FakeLLM(_PLAN_DIRECT, _REWRITE, ["Hello! How can I help?"])
    final = await _run_graph(fake, [], question="Hello!")
    assert final["answer"] == "Hello! How can I help?"
    assert final["citations"] == []
    assert final["verify_result"] == "skipped"
    assert fake.direct_calls == 1
    assert fake.reasoning_calls == 0


@pytest.mark.asyncio
async def test_good_retrieval_verify_pass() -> None:
    fake = _FakeLLM(_PLAN_RETRIEVE, _REWRITE, [_GOOD_ANSWER])
    final = await _run_graph(fake, [[_GOOD_CHUNK()]])
    assert final["answer"] == "Paris is the capital."
    assert len(final["citations"]) == 1
    assert final["citations"][0]["chunk_id"] == "c-good"
    assert final["retrieval_grade"] == "good"
    assert final["verify_result"] == "pass"
    assert final["retries"] == 0
    assert final["verify_attempts"] == 0


@pytest.mark.asyncio
async def test_poor_retrieval_rewrite_retry_then_good() -> None:
    fake = _FakeLLM(_PLAN_RETRIEVE, _REWRITE, [_GOOD_ANSWER])
    final = await _run_graph(fake, [[_LOW_CHUNK()], [_GOOD_CHUNK()]])
    assert fake.rewrite_calls == 1
    assert final["retries"] == 1
    assert final["retrieval_grade"] == "good"
    assert final["answer"] == "Paris is the capital."
    assert final["citations"][0]["chunk_id"] == "c-good"


@pytest.mark.asyncio
async def test_poor_after_retry_refuses_without_reasoning() -> None:
    # Behaviour changed by grade-based refusal (2026-10-26): a still-
    # poor grade after the single rewrite goes to the refuse node,
    # not to reasoning. The old name asserted the previous behaviour.
    fake = _FakeLLM(_PLAN_RETRIEVE, _REWRITE, [_LOW_ANSWER])
    final = await _run_graph(fake, [[_LOW_CHUNK()], [_LOW_CHUNK()]])
    assert fake.rewrite_calls == 1  # exactly one retry, never a second
    assert final["retries"] == 1
    assert final["retrieval_grade"] == "poor"
    assert final["answer"] == "I couldn't find relevant information in your documents."
    assert final["citations"] == []
    assert final["verify_result"] == "skipped"
    assert fake.reasoning_calls == 0


@pytest.mark.asyncio
async def test_empty_after_retry_refuses() -> None:
    fake = _FakeLLM(_PLAN_RETRIEVE, _REWRITE, ["anything"])
    final = await _run_graph(fake, [[], []])
    assert final["retries"] == 1
    assert "couldn't find" in final["answer"]
    assert final["citations"] == []
    assert final["verify_result"] == "skipped"


@pytest.mark.asyncio
async def test_verify_fail_regenerates_once_then_passes() -> None:
    fake = _FakeLLM(_PLAN_RETRIEVE, _REWRITE, [_BAD_ANSWER, _GOOD_ANSWER])
    final = await _run_graph(fake, [[_GOOD_CHUNK()]])
    assert fake.reasoning_calls == 2
    assert final["verify_attempts"] == 1
    assert final["verify_result"] == "pass"
    assert final["answer"] == "Paris is the capital."


@pytest.mark.asyncio
async def test_verify_fail_twice_refuses() -> None:
    fake = _FakeLLM(_PLAN_RETRIEVE, _REWRITE, [_BAD_ANSWER, _BAD_ANSWER])
    final = await _run_graph(fake, [[_GOOD_CHUNK()]])
    assert fake.reasoning_calls == 2  # one regeneration, never a third
    assert final["verify_attempts"] == 2
    assert "couldn't find" in final["answer"]
    assert final["citations"] == []


@pytest.mark.asyncio
async def test_verify_fail_unknown_citation_id_refuses_after_regeneration() -> None:
    unknown = "No evidence here.\n\nCITATIONS:\n[no-such-id] facts.txt, chunk 0"
    fake = _FakeLLM(_PLAN_RETRIEVE, _REWRITE, [unknown, unknown])
    final = await _run_graph(fake, [[_GOOD_CHUNK()]])
    assert "couldn't find" in final["answer"]
    assert final["citations"] == []


@pytest.mark.asyncio
async def test_rewrite_failure_reuses_previous_query_and_records_error() -> None:
    fake = _FakeLLM(_PLAN_RETRIEVE, _REWRITE, [_GOOD_ANSWER], rewrite_raises=True)
    final = await _run_graph(fake, [[_LOW_CHUNK()], [_GOOD_CHUNK()]])
    assert final["retries"] == 1
    assert any("rewrite failed" in e for e in final["errors"])
    assert final["answer"] == "Paris is the capital."


@pytest.mark.asyncio
async def test_retriever_error_raises_agent_error() -> None:
    owner = uuid.uuid4()
    agent = AgentService()
    initial = agent._initial_state("What?", owner, [], None)
    fake = _FakeLLM(_PLAN_RETRIEVE, _REWRITE, ["x"])
    with (
        patch(
            "app.services.agent_service.get_openai_client",
            return_value=_mock_client(fake),
        ),
        patch(
            "app.services.agent_service.EmbeddingService.embed_text",
            new_callable=AsyncMock,
            side_effect=RuntimeError("embedding down"),
        ),
        pytest.raises(AgentError),
    ):
        await _agent_graph.ainvoke(initial)


@pytest.mark.asyncio
async def test_stream_emits_grade_and_verify_status_events() -> None:
    owner = uuid.uuid4()
    agent = AgentService()
    fake = _FakeLLM(_PLAN_RETRIEVE, _REWRITE, [_GOOD_ANSWER])
    with (
        patch(
            "app.services.agent_service.get_openai_client",
            return_value=_mock_client(fake),
        ),
        patch(
            "app.services.agent_service.EmbeddingService.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 3072,
        ),
        patch(
            "app.services.agent_service.VectorStoreService.search",
            new_callable=AsyncMock,
            return_value=[_GOOD_CHUNK()],
        ),
    ):
        events = []
        async for event in agent.run_stream("What is the capital?", owner, [], None):
            events.append(event)
    statuses = [e["status"] for e in events if e["type"] == "status"]
    assert "grading" in statuses
    assert "verifying" in statuses
    assert events[-1]["type"] == "done"
    assert events[-1]["answer"] == "Paris is the capital."
