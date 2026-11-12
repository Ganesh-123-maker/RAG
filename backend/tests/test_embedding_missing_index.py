"""Regression test: embeddings sort must tolerate a missing index.

Gemini's OpenAI-compatible embeddings endpoint returns index=None for
the first item (verified live 2026-11-12: indices None, 1, 2 for a
3-input request). The old `sorted(..., key=lambda x: x.index)` raised
TypeError comparing None with int, so ingestion of every multi-chunk
document failed on Gemini (single-chunk docs never compared, which is
why earlier live runs passed). The fix falls back to response
position when index is None.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.embedding_service import EmbeddingService


class _FakeEmbeddings:
    def __init__(self, data):
        self._data = data

    async def create(self, **kwargs):
        return SimpleNamespace(data=self._data)


class _FakeClient:
    def __init__(self, data):
        self.embeddings = _FakeEmbeddings(data)


@pytest.mark.asyncio
async def test_embed_batch_tolerates_missing_index() -> None:
    data = [
        SimpleNamespace(index=None, embedding=[0.1, 0.2]),
        SimpleNamespace(index=1, embedding=[0.3, 0.4]),
        SimpleNamespace(index=2, embedding=[0.5, 0.6]),
    ]
    svc = EmbeddingService()
    # The service captures its client at construction; rebind it to the fake.
    svc._client = _FakeClient(data)
    vectors = await svc.embed_batch(["a", "b", "c"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]


@pytest.mark.asyncio
async def test_embed_batch_respects_index_order() -> None:
    # Out-of-order indices must still be reordered by index.
    data = [
        SimpleNamespace(index=2, embedding=[0.5, 0.6]),
        SimpleNamespace(index=0, embedding=[0.1, 0.2]),
        SimpleNamespace(index=1, embedding=[0.3, 0.4]),
    ]
    svc = EmbeddingService()
    svc._client = _FakeClient(data)
    vectors = await svc.embed_batch(["a", "b", "c"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
