from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.main as main_module
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.user import User
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.user_repository import UserRepository
from app.services.agent_service import AgentService, planner_node
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingError
from app.services.vector_store_service import RetrievedChunk


def _mock_llm(
    plan_content: str, reasoning_content: str, stream_tokens: list[str] | None = None
):
    """Mock OpenAI client: planner -> plan JSON, reasoning -> answer.

    If ``stream_tokens`` is given, a reasoning call with ``stream=True``
    returns an async generator of those tokens instead of a response object.
    """
    mock_client = MagicMock()

    async def fake_create(*args, **kwargs):
        if kwargs.get("response_format"):
            resp = MagicMock()
            choice = MagicMock()
            choice.message.content = plan_content
            resp.choices = [choice]
            return resp
        if kwargs.get("stream"):

            async def gen():
                for tok in stream_tokens or []:
                    chunk = MagicMock()
                    delta = MagicMock()
                    delta.content = tok
                    chunk.choices = [MagicMock(delta=delta)]
                    yield chunk

            return gen()
        resp = MagicMock()
        choice = MagicMock()
        choice.message.content = reasoning_content
        resp.choices = [choice]
        return resp

    mock_client.chat.completions.create = AsyncMock(side_effect=fake_create)
    return mock_client


_CHUNK = RetrievedChunk(
    text="The capital of France is Paris.",
    document_id=str(uuid.uuid4()),
    document_name="facts.txt",
    chunk_index=0,
    score=0.97,
)


@pytest.mark.asyncio
async def test_embedding_failure_marks_error_and_cleans_up(
    db_session: AsyncSession, fake_user, tmp_path, monkeypatch
) -> None:
    """A1: embedding failure -> EmbeddingError path, safe message, cleanup.

    The raw exception text (including a sentinel secret) must NOT appear
    in the stored error message or the HTTP detail.
    """
    import app.services.document_service as doc_svc_mod

    monkeypatch.setattr(doc_svc_mod.settings, "UPLOAD_DIR", str(tmp_path))

    svc = DocumentService(db_session)
    with (
        patch.object(
            svc._embed_svc,
            "embed_batch",
            new_callable=AsyncMock,
            side_effect=EmbeddingError("boom SECRET_SENTINEL"),
        ),
        patch.object(svc._vector_svc, "ensure_collection", new_callable=AsyncMock),
        patch.object(
            svc._vector_svc, "upsert_chunks", new_callable=AsyncMock
        ) as mock_upsert,
        patch.object(
            svc._vector_svc, "delete_by_document", new_callable=AsyncMock
        ) as mock_delete,
    ):
        file = UploadFile(
            filename="doc.txt", file=io.BytesIO(b"Some document content here.")
        )
        with pytest.raises(Exception) as exc_info:
            await svc.ingest(file, fake_user.id)
        assert exc_info.value.status_code in (502, 500)
        assert "SECRET_SENTINEL" not in str(exc_info.value.detail)
        # Embeddings never succeeded, so nothing was upserted.
        mock_upsert.assert_not_called()

    repo = DocumentRepository(db_session)
    docs = await repo.get_by_owner(fake_user.id)
    assert len(docs) == 1
    assert docs[0].status == "error"
    assert "SECRET_SENTINEL" not in (docs[0].error_message or "")
    # No files left behind.
    assert list(tmp_path.rglob("*")) == []
    mock_delete.assert_not_called()  # nothing was upserted to clean up


@pytest.mark.asyncio
async def test_ingestion_cleanup_after_upsert(
    db_session: AsyncSession, fake_user, tmp_path, monkeypatch
) -> None:
    """A1: a failure AFTER upsert still removes vectors and the file."""
    import app.services.document_service as doc_svc_mod

    monkeypatch.setattr(doc_svc_mod.settings, "UPLOAD_DIR", str(tmp_path))

    svc = DocumentService(db_session)
    with (
        patch.object(
            svc._embed_svc,
            "embed_batch",
            new_callable=AsyncMock,
            return_value=[[0.1] * 3072],
        ),
        patch.object(svc._vector_svc, "ensure_collection", new_callable=AsyncMock),
        patch.object(svc._vector_svc, "upsert_chunks", new_callable=AsyncMock),
        patch.object(
            svc._vector_svc, "delete_by_document", new_callable=AsyncMock
        ) as mock_delete,
        patch.object(
            svc._doc_repo,
            "mark_ready",
            new_callable=AsyncMock,
            side_effect=RuntimeError("SECRET_SENTINEL mark failure"),
        ),
    ):
        file = UploadFile(
            filename="doc.txt", file=io.BytesIO(b"Some document content here.")
        )
        with pytest.raises(Exception) as exc_info:
            await svc.ingest(file, fake_user.id)
        assert "SECRET_SENTINEL" not in str(exc_info.value.detail)
    mock_delete.assert_awaited_once()
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_stream_nonstream_equivalence() -> None:
    """A2: same graph, same fixture -> same answer and citations."""
    plan = '{"needs_retrieval": true, "retrieval_query": "capital of France"}'
    reasoning = "Paris.\n\nCITATIONS:\n[1] facts.txt, chunk 0"
    owner_id = uuid.uuid4()

    with (
        patch(
            "app.services.agent_service.get_openai_client",
            return_value=_mock_llm(
                plan,
                reasoning,
                stream_tokens=["Par", "is.\n\nCITATIONS:\n[1] facts.txt, chunk 0"],
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
            return_value=[_CHUNK],
        ),
    ):
        agent = AgentService()
        result = await agent.run("What is the capital of France?", owner_id)

    with (
        patch(
            "app.services.agent_service.get_openai_client",
            return_value=_mock_llm(
                plan,
                reasoning,
                stream_tokens=["Par", "is.\n\nCITATIONS:\n[1] facts.txt, chunk 0"],
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
            return_value=[_CHUNK],
        ),
    ):
        agent = AgentService()
        events = [
            e
            async for e in agent.run_stream("What is the capital of France?", owner_id)
        ]

    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert done[0]["answer"] == result.answer
    assert done[0]["citations"] == result.citations
    assert result.answer == "Paris."
    assert len(result.citations) == 1
    assert result.citations[0]["document_name"] == "facts.txt"
    assert any(e["type"] == "token" for e in events)
    assert any(e["type"] == "citations" for e in events)


@pytest.mark.asyncio
async def test_planner_skip_direct_answer() -> None:
    """A3: needs_retrieval=False answers directly, never a doc refusal."""
    plan = '{"needs_retrieval": false, "retrieval_query": ""}'
    owner_id = uuid.uuid4()
    with patch(
        "app.services.agent_service.get_openai_client",
        return_value=_mock_llm(plan, "Hello! How can I help?"),
    ):
        agent = AgentService()
        result = await agent.run("Hello", owner_id)
    assert "Hello!" in result.answer
    assert "couldn't find" not in result.answer
    assert result.citations == []


@pytest.mark.asyncio
async def test_planner_invalid_json_fails_open_to_retrieval() -> None:
    """A3: unparseable planner output fails open to retrieval."""
    state = {
        "question": "What is the capital?",
        "owner_id": str(uuid.uuid4()),
        "document_id": None,
        "history": [],
        "retrieval_query": "",
        "chunks": [],
        "answer": "",
        "citations": [],
        "needs_retrieval": False,
    }
    mock_client = MagicMock()
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = "this is not json at all"
    resp.choices = [choice]
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    with patch(
        "app.services.agent_service.get_openai_client", return_value=mock_client
    ):
        out = await planner_node(state)
    assert out["needs_retrieval"] is True
    assert out["retrieval_query"] == "What is the capital?"


@pytest.mark.asyncio
async def test_malformed_jwt_sub_returns_401(db_session: AsyncSession) -> None:
    """A5: a validly signed JWT with a non-UUID sub is 401, not 500."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)
    try:
        token = create_access_token("not-a-uuid")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_inactive_user_returns_401(db_session: AsyncSession) -> None:
    """A5: is_active=False users cannot authenticate."""
    repo = UserRepository(db_session)
    user = await repo.create(
        "inactive@example.com", hash_password("password123"), "Inactive"
    )
    user.is_active = False
    await db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)
    try:
        token = create_access_token(str(user.id))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_owner_scoped_repositories(db_session: AsyncSession) -> None:
    """A5: owner-scoped repo methods refuse cross-owner access."""
    d_repo = DocumentRepository(db_session)
    c_repo = ConversationRepository(db_session)
    u_repo = UserRepository(db_session)
    owner = await u_repo.create("owner@example.com", "hash", "Owner")
    other = await u_repo.create("other@example.com", "hash", "Other")

    doc = await d_repo.create(
        owner_id=owner.id,
        filename="f.txt",
        original_name="f.txt",
        file_type="txt",
        file_size_bytes=10,
    )
    assert await d_repo.get_by_id_for_owner(doc.id, other.id) is None
    assert await d_repo.get_by_id_for_owner(doc.id, owner.id) is not None
    assert await d_repo.delete_for_owner(doc.id, other.id) is False
    assert await d_repo.get_by_id_for_owner(doc.id, owner.id) is not None
    assert await d_repo.delete_for_owner(doc.id, owner.id) is True

    conv = await c_repo.create_conversation(owner.id, title="Chat")
    await c_repo.add_message(conv.id, "user", "hi")
    assert await c_repo.get_messages_for_owner(conv.id, other.id) == []
    assert len(await c_repo.get_messages_for_owner(conv.id, owner.id)) == 1
    assert await c_repo.delete_conversation_for_owner(conv.id, other.id) is False
    assert await c_repo.delete_conversation_for_owner(conv.id, owner.id) is True


@pytest.mark.asyncio
async def test_chat_document_id_checks(
    test_client: AsyncClient, db_session: AsyncSession, fake_user: User
) -> None:
    """A5: chat with another owner's doc -> 404; non-ready doc -> 409."""
    d_repo = DocumentRepository(db_session)
    doc = await d_repo.create(
        owner_id=fake_user.id,
        filename="f.txt",
        original_name="f.txt",
        file_type="txt",
        file_size_bytes=10,
    )
    # status is "processing" by default -> 409
    with patch("app.routers.chat.AgentService.run", new_callable=AsyncMock) as mock_run:
        resp = await test_client.post(
            "/api/v1/chat/", json={"question": "Q?", "document_id": str(doc.id)}
        )
        assert resp.status_code == 409
        mock_run.assert_not_called()

    await d_repo.mark_ready(doc.id, chunk_count=1, owner_id=fake_user.id)
    resp = await test_client.post(
        "/api/v1/chat/", json={"question": "Q?", "document_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ready_endpoint() -> None:
    """A4: /ready is 200 when deps are up, 503 when either is down."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with (
            patch.object(main_module, "_check_database", new_callable=AsyncMock),
            patch.object(main_module, "_check_qdrant", new_callable=AsyncMock),
        ):
            resp = await client.get("/ready")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ready"

        with (
            patch.object(
                main_module,
                "_check_database",
                new_callable=AsyncMock,
                side_effect=RuntimeError("pg down"),
            ),
            patch.object(main_module, "_check_qdrant", new_callable=AsyncMock),
        ):
            resp = await client.get("/ready")
            assert resp.status_code == 503
            assert "database" in resp.json()["failures"]

        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_stream_error_persists_partial_answer(
    test_client: AsyncClient, db_session: AsyncSession, fake_user: User
) -> None:
    """A2: a stream that errors after tokens still persists the partial answer."""

    async def partial_then_error(self, **kwargs):
        yield {"type": "status", "status": "started"}
        yield {"type": "token", "token": "Partial answer"}
        yield {"type": "error", "detail": "Chat service is temporarily unavailable."}

    with patch("app.routers.chat.AgentService.run_stream", partial_then_error):
        resp = await test_client.post("/api/v1/chat/stream", json={"question": "Q?"})
        assert resp.status_code == 200
        assert "error" in resp.text

    convs = await test_client.get("/api/v1/chat/conversations")
    conv_id = convs.json()["conversations"][0]["id"]
    detail = await test_client.get(f"/api/v1/chat/conversations/{conv_id}")
    messages = detail.json()["messages"]
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant) == 1
    assert "Partial answer" in assistant[0]["content"]
