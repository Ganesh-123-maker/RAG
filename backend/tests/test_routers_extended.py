from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.agent_service as agent_service_mod
from app.core.config import Settings, configure_logging, get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.main import app, lifespan
from app.models.document import Document
from app.models.user import User
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.user_repository import UserRepository
from app.services.agent_service import AgentService
from app.services.rag_service import RagAnswer


@pytest.mark.asyncio
async def test_config_cors_parsing() -> None:
    # Test parse_cors with various inputs
    res_list = Settings.parse_cors(["http://localhost:3000"])
    assert res_list == ["http://localhost:3000"]

    res_json_str = Settings.parse_cors(
        '["http://localhost:3000", "http://127.0.0.1:3000"]'
    )
    assert len(res_json_str) == 2

    res_comma_str = Settings.parse_cors("http://localhost:3000, https://app.vercel.app")
    assert len(res_comma_str) == 2

    res_invalid_json = Settings.parse_cors("[invalid json")
    assert res_invalid_json == ["[invalid json"]


@pytest.mark.asyncio
async def test_security_and_jwt() -> None:
    _settings = get_settings()
    pwd = "mysecretpassword123"
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed)
    assert not verify_password("wrongpassword", hashed)

    # Token creation & decoding
    user_id = str(uuid.uuid4())
    token = create_access_token(subject=user_id, expires_delta=timedelta(minutes=15))
    decoded = decode_access_token(token)
    assert decoded["sub"] == user_id


@pytest.mark.asyncio
async def test_dependencies_and_auth_middleware(db_session: AsyncSession) -> None:
    settings = get_settings()
    user_repo = UserRepository(db_session)
    user = await user_repo.create(
        "auth_test@example.com", hash_password("pass1234"), "Auth Tester"
    )

    # Valid token
    valid_token = create_access_token(subject=str(user.id))
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # GET /api/v1/auth/me with valid token
        resp = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {valid_token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "auth_test@example.com"

        # Invalid token
        resp_invalid = await client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert resp_invalid.status_code == 401

        # Token with nonexistent user
        ghost_token = create_access_token(subject=str(uuid.uuid4()))
        resp_ghost = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {ghost_token}"}
        )
        assert resp_ghost.status_code == 401

        # Token without sub
        bad_payload_token = jwt.encode(
            {"name": "noname"},
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp_bad = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {bad_payload_token}"}
        )
        assert resp_bad.status_code == 401

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_auth_login_variations(db_session: AsyncSession) -> None:
    user_repo = UserRepository(db_session)
    await user_repo.create(
        "form_user@example.com", hash_password("formpassword"), "Form User"
    )

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # JSON login
        resp_json = await client.post(
            "/api/v1/auth/login",
            json={"email": "form_user@example.com", "password": "formpassword"},
        )
        assert resp_json.status_code == 200
        assert "access_token" in resp_json.json()

        # Form login
        resp_form = await client.post(
            "/api/v1/auth/login",
            data={"username": "form_user@example.com", "password": "formpassword"},
        )
        assert resp_form.status_code == 200
        assert "access_token" in resp_form.json()

        # Empty body
        resp_empty = await client.post(
            "/api/v1/auth/login",
            headers={"Content-Type": "application/json"},
            content=b"",
        )
        assert resp_empty.status_code == 422

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_database_generator(db_session: AsyncSession) -> None:
    gen = get_db()
    session = await anext(gen)
    assert session is not None
    await gen.aclose()


@pytest.mark.asyncio
async def test_models_repr() -> None:
    u = User(email="test@repr.com", hashed_password="pw", full_name="Repr")
    assert "test@repr.com" in repr(u)

    d = Document(
        filename="f.txt", original_name="orig.txt", file_type="txt", file_size_bytes=100
    )
    assert "orig.txt" in repr(d)


@pytest.mark.asyncio
async def test_repositories_complete(db_session: AsyncSession) -> None:
    u_repo = UserRepository(db_session)
    d_repo = DocumentRepository(db_session)
    c_repo = ConversationRepository(db_session)

    user = await u_repo.create("repo_test@example.com", "hash", "Repo User")
    assert await u_repo.exists_by_email("repo_test@example.com")
    assert not await u_repo.exists_by_email("nonexistent@example.com")

    by_id = await u_repo.get_by_id(user.id)
    assert by_id is not None

    by_email = await u_repo.get_by_email("repo_test@example.com")
    assert by_email is not None

    # Document repo
    doc = await d_repo.create(
        owner_id=user.id,
        filename="saved.txt",
        original_name="test.txt",
        file_type="txt",
        file_size_bytes=1024,
    )
    assert doc.status == "processing"

    await d_repo.mark_ready(doc.id, chunk_count=5)
    doc_ready = await d_repo.get_by_id(doc.id)
    assert doc_ready.status == "ready"
    assert doc_ready.chunk_count == 5

    await d_repo.mark_error(doc.id, "error occurred")
    doc_err = await d_repo.get_by_id(doc.id)
    assert doc_err.status == "error"
    assert doc_err.error_message == "error occurred"

    docs_list = await d_repo.get_by_owner(user.id)
    assert len(docs_list) == 1

    await d_repo.delete(doc.id)
    assert await d_repo.get_by_id(doc.id) is None

    # Conversation repo
    conv = await c_repo.create_conversation(user.id, title="Test Chat")
    _msg1 = await c_repo.add_message(conv.id, "user", "Hi")
    _msg2 = await c_repo.add_message(
        conv.id, "assistant", "Hello", citations_json='[{"document_name": "d.txt"}]'
    )

    conv_fetched = await c_repo.get_conversation(conv.id, user.id)
    assert conv_fetched is not None
    assert len(conv_fetched.messages) == 2

    messages = await c_repo.get_messages(conv.id)
    assert len(messages) == 2

    conv_list = await c_repo.list_conversations(user.id)
    assert len(conv_list) == 1

    await c_repo.delete_conversation(conv.id)
    assert await c_repo.get_conversation(conv.id, user.id) is None


@pytest.mark.asyncio
async def test_chat_stream_endpoint(
    test_client: AsyncClient, db_session: AsyncSession, fake_user: User
) -> None:
    # Phase A: /stream runs the same AgentService as /chat. Patch the
    # service's run_stream (the graph boundary), not the old inline LLM.
    c_repo = ConversationRepository(db_session)
    existing_conv = await c_repo.create_conversation(fake_user.id, title="Stream Conv")

    async def fake_stream(self, **kwargs):
        yield {"type": "status", "status": "started"}
        yield {"type": "token", "token": "Hello "}
        yield {"type": "token", "token": "world!"}
        yield {"type": "citations", "citations": []}
        yield {"type": "done", "answer": "Hello world!", "citations": []}

    with patch("app.routers.chat.AgentService.run_stream", fake_stream):
        # Stream with existing conversation_id
        response = await test_client.post(
            "/api/v1/chat/stream",
            json={
                "question": "Stream this answer",
                "conversation_id": str(existing_conv.id),
            },
        )
        assert response.status_code == 200
        content = response.text
        assert "Hello " in content
        assert "world!" in content
        assert "done" in content

        # Stream with invalid conversation_id
        resp_404 = await test_client.post(
            "/api/v1/chat/stream",
            json={"question": "Stream question", "conversation_id": str(uuid.uuid4())},
        )
        assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_chat_stream_fallback(test_client: AsyncClient) -> None:
    # Phase A: a stream failure now yields a structured error event, not a
    # fabricated snippet "answer" followed by done.
    async def failing_stream(self, **kwargs):
        yield {"type": "status", "status": "started"}
        yield {"type": "error", "detail": "Chat service is temporarily unavailable."}

    with patch("app.routers.chat.AgentService.run_stream", failing_stream):
        response = await test_client.post(
            "/api/v1/chat/stream",
            json={"question": "Fallback question"},
        )
        assert response.status_code == 200
        assert "error" in response.text
        assert "Based" not in response.text


@pytest.mark.asyncio
async def test_chat_errors_and_document_id(
    test_client: AsyncClient, db_session: AsyncSession, fake_user: User
) -> None:
    # Phase A: chat's document_id is now ownership- + status-checked, so
    # the test uses a real ready document owned by the test user; a random
    # id must 404 instead of silently searching nothing.
    d_repo = DocumentRepository(db_session)
    doc = await d_repo.create(
        owner_id=fake_user.id,
        filename="d.txt",
        original_name="d.txt",
        file_type="txt",
        file_size_bytes=100,
    )
    await d_repo.mark_ready(doc.id, chunk_count=1, owner_id=fake_user.id)
    doc_id = doc.id
    mock_result = RagAnswer(
        answer="Direct answer with doc.",
        citations=[
            {
                "document_id": str(doc_id),
                "document_name": "d.txt",
                "chunk_index": 0,
                "score": 0.9,
                "snippet": "...",
            }
        ],
    )

    with patch(
        "app.services.agent_service.AgentService.run",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = await test_client.post(
            "/api/v1/chat/",
            json={"question": "Question with doc", "document_id": str(doc_id)},
        )
        assert resp.status_code == 201
        assert resp.json()["content"] == "Direct answer with doc."
        assert len(resp.json()["citations"]) == 1

        # Nonexistent document ID -> 404 (Phase A document check)
        resp_doc404 = await test_client.post(
            "/api/v1/chat/",
            json={"question": "Question bad doc", "document_id": str(uuid.uuid4())},
        )
        assert resp_doc404.status_code == 404

        # Nonexistent conversation ID
        resp_404 = await test_client.post(
            "/api/v1/chat/",
            json={
                "question": "Question bad conv",
                "conversation_id": str(uuid.uuid4()),
            },
        )
        assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_document_wrong_owner(
    test_client: AsyncClient, db_session: AsyncSession
) -> None:
    # Create document under another user
    other_user = User(
        id=uuid.uuid4(),
        email="other@example.com",
        hashed_password="pw",
        full_name="Other",
    )
    db_session.add(other_user)
    await db_session.flush()

    d_repo = DocumentRepository(db_session)
    doc = await d_repo.create(
        owner_id=other_user.id,
        filename="other.txt",
        original_name="other.txt",
        file_type="txt",
        file_size_bytes=100,
    )

    # Current user tries to access other user's document
    resp_get = await test_client.get(f"/api/v1/documents/{doc.id}")
    assert resp_get.status_code == 404

    resp_del = await test_client.delete(f"/api/v1/documents/{doc.id}")
    assert resp_del.status_code == 404


@pytest.mark.asyncio
async def test_conversation_wrong_owner(
    test_client: AsyncClient, db_session: AsyncSession
) -> None:
    other_user_id = uuid.uuid4()
    c_repo = ConversationRepository(db_session)
    conv = await c_repo.create_conversation(other_user_id, title="Other's Conv")

    resp_get = await test_client.get(f"/api/v1/chat/conversations/{conv.id}")
    assert resp_get.status_code == 404

    resp_del = await test_client.delete(f"/api/v1/chat/conversations/{conv.id}")
    assert resp_del.status_code == 404


@pytest.mark.asyncio
async def test_get_document_success(
    test_client: AsyncClient, db_session: AsyncSession, fake_user: User
) -> None:
    d_repo = DocumentRepository(db_session)
    doc = await d_repo.create(
        owner_id=fake_user.id,
        filename="abc.pdf",
        original_name="manual.pdf",
        file_type="pdf",
        file_size_bytes=2048,
    )
    await d_repo.mark_ready(doc.id, chunk_count=2)

    resp = await test_client.get(f"/api/v1/documents/{doc.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["original_name"] == "manual.pdf"
    assert data["chunk_count"] == 2


@pytest.mark.asyncio
async def test_get_conversation_success(
    test_client: AsyncClient, db_session: AsyncSession, fake_user: User
) -> None:
    c_repo = ConversationRepository(db_session)
    conv = await c_repo.create_conversation(fake_user.id, title="Sample Conversation")
    await c_repo.add_message(conv.id, "user", "Hello")
    await c_repo.add_message(
        conv.id,
        "assistant",
        "Hi there!",
        citations_json='[{"document_id": "1", "document_name": "d.txt", "chunk_index": 0, "score": 0.9, "snippet": "..."}]',
    )

    resp = await test_client.get(f"/api/v1/chat/conversations/{conv.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Sample Conversation"
    assert len(data["messages"]) == 2
    assert len(data["messages"][1]["citations"]) == 1


@pytest.mark.asyncio
async def test_main_health_and_lifespan() -> None:
    configure_logging("DEBUG")
    async with lifespan(app):
        pass

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_agent_service_full_run() -> None:
    agent = AgentService()
    owner_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    mock_state_output = {
        "answer": "Graph Answer",
        "citations": [
            {
                "document_id": str(doc_id),
                "document_name": "doc.txt",
                "chunk_index": 0,
                "score": 0.9,
                "snippet": "...",
            }
        ],
    }

    with patch.object(
        agent_service_mod,
        "_agent_graph",
        MagicMock(ainvoke=AsyncMock(return_value=mock_state_output)),
    ):
        result = await agent.run(
            "Full test question", owner_id, history=[], document_id=doc_id
        )
        assert result.answer == "Graph Answer"
        assert len(result.citations) == 1
