from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.rag_service import RagAnswer


@pytest.mark.asyncio
async def test_list_conversations_empty(test_client: AsyncClient) -> None:
    response = await test_client.get("/api/v1/chat/conversations")
    assert response.status_code == 200
    data = response.json()
    assert data["conversations"] == []


@pytest.mark.asyncio
async def test_chat_creates_conversation(test_client: AsyncClient) -> None:
    mock_result = RagAnswer(
        answer="The document says X.",
        citations=[
            {
                "document_id": str(uuid.uuid4()),
                "document_name": "test.txt",
                "chunk_index": 0,
                "score": 0.95,
                "snippet": "The document says X.",
            }
        ],
    )

    with patch(
        "app.services.agent_service.AgentService.run",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        response = await test_client.post(
            "/api/v1/chat/",
            json={"question": "What does the document say?"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "assistant"
    assert data["content"] == "The document says X."
    assert len(data["citations"]) == 1


@pytest.mark.asyncio
async def test_chat_continues_existing_conversation(test_client: AsyncClient) -> None:
    mock_result = RagAnswer(answer="First answer.", citations=[])

    with patch(
        "app.services.agent_service.AgentService.run",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        first = await test_client.post(
            "/api/v1/chat/",
            json={"question": "First question"},
        )
    assert first.status_code == 201

    convs = await test_client.get("/api/v1/chat/conversations")
    assert convs.status_code == 200
    conv_id = convs.json()["conversations"][0]["id"]

    mock_result2 = RagAnswer(answer="Follow-up answer.", citations=[])
    with patch(
        "app.services.agent_service.AgentService.run",
        new_callable=AsyncMock,
        return_value=mock_result2,
    ):
        second = await test_client.post(
            "/api/v1/chat/",
            json={"question": "Follow-up question", "conversation_id": conv_id},
        )
    assert second.status_code == 201
    assert second.json()["content"] == "Follow-up answer."


@pytest.mark.asyncio
async def test_get_conversation_not_found(test_client: AsyncClient) -> None:
    random_id = uuid.uuid4()
    response = await test_client.get(f"/api/v1/chat/conversations/{random_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_conversation(test_client: AsyncClient) -> None:
    mock_result = RagAnswer(answer="Answer.", citations=[])

    with patch(
        "app.services.agent_service.AgentService.run",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        created = await test_client.post(
            "/api/v1/chat/",
            json={"question": "Delete me"},
        )
    assert created.status_code == 201

    convs = await test_client.get("/api/v1/chat/conversations")
    conv_id = convs.json()["conversations"][0]["id"]

    delete_resp = await test_client.delete(f"/api/v1/chat/conversations/{conv_id}")
    assert delete_resp.status_code == 204

    convs_after = await test_client.get("/api/v1/chat/conversations")
    assert convs_after.json()["conversations"] == []


@pytest.mark.asyncio
async def test_delete_conversation_not_found(test_client: AsyncClient) -> None:
    random_id = uuid.uuid4()
    response = await test_client.delete(f"/api/v1/chat/conversations/{random_id}")
    assert response.status_code == 404
