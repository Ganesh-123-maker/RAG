from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_documents_empty(test_client: AsyncClient) -> None:
    response = await test_client.get("/api/v1/documents/")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["documents"] == []


@pytest.mark.asyncio
async def test_upload_document_txt(test_client: AsyncClient) -> None:
    fake_embeddings = [[0.1] * 3072]
    txt_content = b"This is a test document with enough content to create at least one chunk."

    with (
        patch(
            "app.services.embedding_service.EmbeddingService.embed_batch",
            new_callable=AsyncMock,
            return_value=fake_embeddings,
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
        response = await test_client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.txt", io.BytesIO(txt_content), "text/plain")},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["original_name"] == "test.txt"
    assert data["file_type"] == "txt"
    assert data["status"] == "ready"
    assert data["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_upload_document_unsupported_type(test_client: AsyncClient) -> None:
    response = await test_client.post(
        "/api/v1/documents/upload",
        files={"file": ("test.exe", io.BytesIO(b"binary"), "application/octet-stream")},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_document_not_found(test_client: AsyncClient) -> None:
    random_id = uuid.uuid4()
    response = await test_client.get(f"/api/v1/documents/{random_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_not_found(test_client: AsyncClient) -> None:
    random_id = uuid.uuid4()
    response = await test_client.delete(f"/api/v1/documents/{random_id}")
    assert response.status_code == 404
