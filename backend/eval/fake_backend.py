"""Deterministic fake backends for OFFLINE evaluation only.

These exist for one purpose: proving the eval pipeline works end to
end (ingest -> retrieve -> graph -> metrics -> output) without spending
any money or calling any external service. They must NEVER be used to
report quality numbers: a hashed bag-of-words embedding and a fake LLM
that copies the best-overlapping context chunk cannot measure whether
the real system answers well. Every offline result file carries
``mode: "offline-pipeline-smoke"`` and the report says so in words.

Fake embedding: feature-hashed bag of words into 3072 dimensions
(the production embedding size, so the Qdrant collection shape is
unchanged), L2-normalised. Cosine similarity then approximates token
overlap, which is why retrieval can hit the right document offline
without any learned semantics.

Fake LLM: inspects the messages it is given.
- Planner prompts return JSON ``needs_retrieval`` (false only for
  greetings / simple arithmetic, mirroring the production planner's
  stated rule); otherwise the raw question as the retrieval query.
- Rewrite prompts return the original question as the new query.
- Reasoning prompts parse the ``<context>`` blocks, return the block
  with the highest token overlap with the question, and cite it by
  its chunk id. If there is no usable context, it returns the shared
  refusal text.
- Direct-answer prompts return a short greeting answer.
"""

from __future__ import annotations

import hashlib
import json
import math
import re

DIMENSIONS = 3072

_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "by",
    "at",
    "from",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "as",
    "what",
    "which",
    "who",
    "when",
    "where",
    "how",
    "why",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "will",
    "shall",
    "may",
    "might",
    "i",
    "you",
    "he",
    "she",
    "we",
    "they",
    "his",
    "her",
    "their",
    "our",
}

REFUSAL_TEXT = "I couldn't find relevant information in your documents."


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


def fake_vector(text: str) -> list[float]:
    """Feature-hashed bag-of-words vector, L2-normalised."""
    vec = [0.0] * DIMENSIONS
    for tok in _tokens(text):
        bucket = int(hashlib.sha256(tok.encode()).hexdigest(), 16) % DIMENSIONS
        vec[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


class FakeEmbeddingService:
    """Drop-in for EmbeddingService in offline mode only."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def embed_text(self, text: str) -> list[float]:
        return fake_vector(text.replace("\n", " "))

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [fake_vector(t.replace("\n", " ")) for t in texts]


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    async def create(self, **kwargs):
        messages = kwargs.get("messages", [])
        system = ""
        user = ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
            if m.get("role") == "user":
                user = m.get("content", "")
        if "query planner" in system:
            question = ""
            for line in user.splitlines():
                if line.startswith("Current question:"):
                    question = line.split(":", 1)[1].strip()
            lowered = question.lower().strip()
            if lowered in ("hello", "hi", "hey", "hello!", "hi!"):
                return _FakeResponse(
                    json.dumps({"needs_retrieval": False, "retrieval_query": ""})
                )
            if re.fullmatch(r"[0-9\s+\-*/().]+", lowered) and any(
                c.isdigit() for c in lowered
            ):
                return _FakeResponse(
                    json.dumps({"needs_retrieval": False, "retrieval_query": ""})
                )
            return _FakeResponse(
                json.dumps({"needs_retrieval": True, "retrieval_query": question})
            )
        if "DIFFERENT self-contained retrieval query" in user:
            original = ""
            for line in user.splitlines():
                if line.startswith("Original question:"):
                    original = line.split(":", 1)[1].strip()
            return _FakeResponse(json.dumps({"retrieval_query": original}))
        if "precise research assistant" in system:
            blocks = re.findall(
                r'<context id="([^"]+)" document="([^"]+)" chunk="(\d+)"[^>]*>\n(.*?)\n</context>',
                user,
                flags=re.DOTALL,
            )
            if not blocks:
                return _FakeResponse(REFUSAL_TEXT)
            question = user.split("Question:", 1)[-1] if "Question:" in user else user
            q_tokens = set(_tokens(question))
            best = None
            best_overlap = -1
            for chunk_id, doc, chunk_no, text in blocks:
                overlap = len(q_tokens & set(_tokens(text)))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best = (chunk_id, doc, chunk_no, text)
            if best is None or best_overlap <= 0:
                return _FakeResponse(REFUSAL_TEXT)
            chunk_id, doc, chunk_no, text = best
            snippet = " ".join(text.split())
            return _FakeResponse(
                f"{snippet}\n\nCITATIONS:\n[{chunk_id}] {doc}, chunk {chunk_no}"
            )
        # Direct-answer path (greetings / simple questions).
        return _FakeResponse("Hello! I can help with questions about your documents.")


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class FakeLLMClient:
    """Drop-in for AsyncOpenAI in offline mode only (non-streaming)."""

    def __init__(self) -> None:
        self.chat = _FakeChat()
