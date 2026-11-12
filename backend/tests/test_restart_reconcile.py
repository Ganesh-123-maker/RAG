"""Restart recovery: a 'ready' document whose vectors are gone.

Regression test for the 2026-11-12 E2E finding: after a backend restart
with the volatile ``:memory:`` Qdrant store, documents still said
``ready`` in the DB but had no retrievable vectors, so chat refused
every question about them -- and the content-hash dedupe returned the
same stale row on re-upload, so the user had no self-service recovery.
The fix re-queues such rows at startup so the ingestion worker
re-indexes them from the stored file.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.document_repository import DocumentRepository
from app.services.chunking_service import TextChunk
from app.services.document_service import DocumentService
from app.services.vector_store_service import VectorStoreService


async def _make_ready_doc(
    db_session: AsyncSession, tmp_path, monkeypatch, *, with_file: bool
) -> tuple[uuid.UUID, uuid.UUID]:
    import app.services.document_service as doc_mod

    monkeypatch.setattr(doc_mod.settings, "UPLOAD_DIR", str(tmp_path))
    owner = uuid.uuid4()
    repo = DocumentRepository(db_session)
    doc = await repo.create(
        owner_id=owner,
        filename="ready.txt",
        original_name="ready.txt",
        file_type="txt",
        file_size_bytes=50,
        status="ready",
    )
    if with_file:
        upload_dir = tmp_path / str(owner)
        upload_dir.mkdir(parents=True)
        (upload_dir / "ready.txt").write_bytes(
            b"Ready document with enough content to chunk and index."
        )
    await db_session.commit()
    return owner, doc.id


@pytest.mark.asyncio
async def test_requeue_ready_doc_missing_vectors(
    db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    owner, doc_id = await _make_ready_doc(
        db_session, tmp_path, monkeypatch, with_file=True
    )
    svc = DocumentService(db_session)
    vector_store = VectorStoreService()
    vector_store.count_for_document = AsyncMock(return_value=0)  # type: ignore[method-assign]
    result = await svc.requeue_ready_documents_missing_vectors(vector_store)
    assert result == {"checked": 1, "requeued": 1, "skipped_missing_file": 0}
    finished = await DocumentRepository(db_session).get_by_id_for_owner(doc_id, owner)
    assert finished is not None
    assert finished.status == "queued"
    assert finished.ingestion_progress == 0


@pytest.mark.asyncio
async def test_requeue_keeps_ready_doc_with_vectors(
    db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    owner, doc_id = await _make_ready_doc(
        db_session, tmp_path, monkeypatch, with_file=True
    )
    svc = DocumentService(db_session)
    vector_store = VectorStoreService()
    vector_store.count_for_document = AsyncMock(return_value=3)  # type: ignore[method-assign]
    result = await svc.requeue_ready_documents_missing_vectors(vector_store)
    assert result == {"checked": 1, "requeued": 0, "skipped_missing_file": 0}
    finished = await DocumentRepository(db_session).get_by_id_for_owner(doc_id, owner)
    assert finished is not None
    assert finished.status == "ready"


@pytest.mark.asyncio
async def test_requeue_skips_ready_doc_with_missing_file(
    db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    owner, doc_id = await _make_ready_doc(
        db_session, tmp_path, monkeypatch, with_file=False
    )
    svc = DocumentService(db_session)
    vector_store = VectorStoreService()
    vector_store.count_for_document = AsyncMock(return_value=0)  # type: ignore[method-assign]
    result = await svc.requeue_ready_documents_missing_vectors(vector_store)
    assert result == {"checked": 1, "requeued": 0, "skipped_missing_file": 1}
    assert vector_store.count_for_document.call_count == 0  # type: ignore[attr-defined]
    finished = await DocumentRepository(db_session).get_by_id_for_owner(doc_id, owner)
    assert finished is not None
    assert finished.status == "ready"


@pytest.mark.asyncio
async def test_count_for_document_against_real_memory_store() -> None:
    """count_for_document sees a real upsert and a real delete.

    This is the :memory: Qdrant client the tests and the local stack
    use, so it also proves the count filter matches the payload keys
    upsert_chunks writes.
    """
    owner = uuid.uuid4()
    doc_id = uuid.uuid4()
    svc = VectorStoreService()
    await svc.ensure_collection()
    chunk = TextChunk(
        text="Counting test chunk.",
        chunk_index=0,
        document_id=doc_id,
        document_name="count.txt",
    )
    await svc.upsert_chunks([chunk], [[0.1] * 3072], owner)
    assert await svc.count_for_document(doc_id, owner) == 1
    assert await svc.count_for_document(uuid.uuid4(), owner) == 0
    await svc.delete_by_document(doc_id, owner)
    assert await svc.count_for_document(doc_id, owner) == 0


@pytest.mark.asyncio
async def test_requeued_doc_is_reprocessed_by_worker(
    db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    """End to end of the recovery path: requeue -> worker -> ready."""
    owner, doc_id = await _make_ready_doc(
        db_session, tmp_path, monkeypatch, with_file=True
    )
    svc = DocumentService(db_session)
    vector_store = VectorStoreService()
    vector_store.count_for_document = AsyncMock(return_value=0)  # type: ignore[method-assign]
    await svc.requeue_ready_documents_missing_vectors(vector_store)
    with (
        patch(
            "app.services.embedding_service.EmbeddingService.embed_batch",
            new_callable=AsyncMock,
            return_value=[[0.1] * 3072],
        ),
        patch(
            "app.services.vector_store_service.VectorStoreService.upsert_chunks",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.vector_store_service.VectorStoreService.ensure_collection",
            new_callable=AsyncMock,
        ),
    ):
        result = await svc.process_queued_documents()
    assert result == {"processed": 1, "errored": 0, "total": 1}
    finished = await DocumentRepository(db_session).get_by_id_for_owner(doc_id, owner)
    assert finished is not None
    assert finished.status == "ready"
