from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.user import User
from app.services.agent_service import (
    AgentError,
    AgentService,
    direct_answer_node,
    planner_node,
    reasoning_node,
    response_node,
    retriever_node,
    should_retrieve,
)
from app.services.auth_service import AuthService
from app.services.chunking_service import TextChunk, chunk_text, extract_text, get_tokenizer
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingError, EmbeddingService, get_openai_client
from app.services.rag_service import RagAnswer, parse_citations
from app.services.vector_store_service import (
    RetrievedChunk,
    VectorStoreService,
    get_qdrant_client,
)


@pytest.mark.asyncio
async def test_auth_service(db_session: AsyncSession) -> None:
    svc = AuthService(db_session)
    from app.schemas.auth import RegisterRequest

    # Register
    req = RegisterRequest(email="service_user@example.com", password="password123", full_name="Service User")
    user = await svc.register(req)
    assert user.email == "service_user@example.com"

    # Duplicate register
    with pytest.raises(HTTPException) as exc:
        await svc.register(req)
    assert exc.value.status_code == 409

    # Login success
    token_resp = await svc.login("service_user@example.com", "password123")
    assert token_resp.access_token
    assert token_resp.token_type == "bearer"

    # Login failure
    with pytest.raises(HTTPException) as exc2:
        await svc.login("service_user@example.com", "wrongpass")
    assert exc2.value.status_code == 401

    with pytest.raises(HTTPException) as exc3:
        await svc.login("nonexistent@example.com", "password123")
    assert exc3.value.status_code == 401


@pytest.mark.asyncio
async def test_chunking_service_branches() -> None:
    # Test tokenizer fallback
    tok = get_tokenizer()
    assert tok is not None

    # Empty text chunking
    assert chunk_text("", uuid.uuid4(), "empty.txt") == []
    assert chunk_text("   ", uuid.uuid4(), "empty.txt") == []

    # PDF extraction mock
    with patch("pdfplumber.open") as mock_pdf:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Extracted PDF content page 1"
        mock_pdf_instance = MagicMock()
        mock_pdf_instance.pages = [mock_page]
        mock_pdf_instance.__enter__.return_value = mock_pdf_instance
        mock_pdf_instance.__exit__.return_value = None
        mock_pdf.return_value = mock_pdf_instance

        res = extract_text(b"%PDF-1.4 dummy", "pdf")
        assert "Extracted PDF" in res

    # DOCX extraction mock
    with patch("app.services.chunking_service.DocxDocument") as mock_docx:
        p1 = MagicMock()
        p1.text = "Paragraph 1 text"
        mock_doc_instance = MagicMock()
        mock_doc_instance.paragraphs = [p1]
        mock_docx.return_value = mock_doc_instance

        res_docx = extract_text(b"docx bytes", "docx")
        assert "Paragraph 1" in res_docx

    # Error handling in PDF / DOCX
    with patch("pdfplumber.open", side_effect=RuntimeError("Corrupt PDF")):
        with pytest.raises(ValueError, match="Failed to extract text from PDF"):
            extract_text(b"bad", "pdf")

    with patch("app.services.chunking_service.DocxDocument", side_effect=RuntimeError("Corrupt DOCX")):
        with pytest.raises(ValueError, match="Failed to extract text from DOCX"):
            extract_text(b"bad", "docx")


@pytest.mark.asyncio
async def test_embedding_service() -> None:
    client = get_openai_client()
    assert client is not None

    svc = EmbeddingService()

    # Mock embed_text
    mock_resp = MagicMock()
    mock_data = MagicMock()
    mock_data.embedding = [0.1] * 3072
    mock_resp.data = [mock_data]

    with patch.object(svc._client.embeddings, "create", new_callable=AsyncMock, return_value=mock_resp):
        vec = await svc.embed_text("Hello world\nwith newline")
        assert len(vec) == 3072

    # Mock embed_batch
    mock_item0 = MagicMock(index=0, embedding=[0.1] * 3072)
    mock_item1 = MagicMock(index=1, embedding=[0.2] * 3072)
    mock_batch_resp = MagicMock(data=[mock_item1, mock_item0])

    with patch.object(svc._client.embeddings, "create", new_callable=AsyncMock, return_value=mock_batch_resp):
        vectors = await svc.embed_batch(["text1", "text2"])
        assert len(vectors) == 2
        assert vectors[0] == [0.1] * 3072
        assert vectors[1] == [0.2] * 3072

    # Phase A: no fallback vectors -- OpenAI failure raises EmbeddingError
    # (after tenacity retries) instead of returning substitute vectors.
    with patch.object(svc._client.embeddings, "create", new_callable=AsyncMock, side_effect=RuntimeError("API down")):
        with pytest.raises(EmbeddingError):
            await svc.embed_text("test fallback")

        with pytest.raises(EmbeddingError):
            await svc.embed_batch(["fb1", "fb2"])


@pytest.mark.asyncio
async def test_vector_store_service() -> None:
    q_client = get_qdrant_client()
    assert q_client is not None

    svc = VectorStoreService()
    owner_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    # Mock collection ensure
    mock_collections = MagicMock()
    mock_collections.collections = [MagicMock(name="other_collection")]

    with (
        patch.object(svc._client, "get_collections", new_callable=AsyncMock, return_value=mock_collections),
        patch.object(svc._client, "create_collection", new_callable=AsyncMock) as mock_create,
    ):
        await svc.ensure_collection()
        assert mock_create.called

    # Mock upsert
    chunks = [
        TextChunk(text="Chunk 1", chunk_index=0, document_id=doc_id, document_name="doc.txt"),
    ]
    embeddings = [[0.1] * 3072]

    with patch.object(svc._client, "upsert", new_callable=AsyncMock) as mock_upsert:
        await svc.upsert_chunks(chunks, embeddings, owner_id)
        assert mock_upsert.called

    # Mock search
    mock_result_point = MagicMock()
    mock_result_point.score = 0.95
    mock_result_point.payload = {
        "text": "Chunk 1",
        "document_id": str(doc_id),
        "document_name": "doc.txt",
        "chunk_index": 0,
    }

    with patch.object(svc._client, "search", new_callable=AsyncMock, return_value=[mock_result_point]):
        results = await svc.search(query_vector=[0.1] * 3072, owner_id=owner_id, document_id=doc_id)
        assert len(results) == 1
        assert results[0].text == "Chunk 1"
        assert results[0].score == 0.95

    # Mock delete
    with patch.object(svc._client, "delete", new_callable=AsyncMock) as mock_delete:
        await svc.delete_by_document(doc_id, owner_id)
        assert mock_delete.called


@pytest.mark.asyncio
async def test_document_service_flow(db_session: AsyncSession, tmp_path) -> None:
    from fastapi import UploadFile

    user = User(
        id=uuid.uuid4(),
        email="doc_user@example.com",
        hashed_password="pw",
        full_name="Doc User",
    )
    db_session.add(user)
    await db_session.flush()

    with patch("app.services.document_service.settings.UPLOAD_DIR", str(tmp_path)):
        svc = DocumentService(db_session)

        # Ingest unsupported file
        unsupported = UploadFile(filename="file.exe", file=io.BytesIO(b"bad"))
        with pytest.raises(HTTPException) as exc:
            await svc.ingest(unsupported, user.id)
        assert exc.value.status_code == 422

        # Ingest file exceeding size limit
        large_bytes = b"x" * (51 * 1024 * 1024)
        too_large = UploadFile(filename="large.txt", file=io.BytesIO(large_bytes))
        with patch("app.services.document_service.settings.MAX_UPLOAD_SIZE_MB", 50):
            with pytest.raises(HTTPException) as exc_large:
                await svc.ingest(too_large, user.id)
            assert exc_large.value.status_code == 413

        # Ingest valid TXT file
        valid_file = UploadFile(filename="sample.txt", file=io.BytesIO(b"Valid content for ingestion."))
        with (
            patch.object(svc._embed_svc, "embed_batch", new_callable=AsyncMock, return_value=[[0.1] * 3072]),
            patch.object(svc._vector_svc, "ensure_collection", new_callable=AsyncMock),
            patch.object(svc._vector_svc, "upsert_chunks", new_callable=AsyncMock),
        ):
            doc_id = await svc.ingest(valid_file, user.id)
            assert doc_id is not None

        # Delete document
        with patch.object(svc._vector_svc, "delete_by_document", new_callable=AsyncMock):
            await svc.delete(doc_id, user.id)

        # Delete non-existent document
        with pytest.raises(HTTPException) as exc_404:
            await svc.delete(uuid.uuid4(), user.id)
        assert exc_404.value.status_code == 404

        # Ingestion failure marks error
        error_file = UploadFile(filename="empty.txt", file=io.BytesIO(b"   "))
        with pytest.raises(HTTPException):
            await svc.ingest(error_file, user.id)


@pytest.mark.asyncio
async def test_rag_service() -> None:
    # Phase A: RagService.answer() was deleted (duplicate RAG path); the
    # module now only provides the citation parser used by the agent.
    mock_chunks = [
        RetrievedChunk(
            text="Antigravity is an IDE.",
            document_id=str(uuid.uuid4()),
            document_name="guide.txt",
            chunk_index=0,
            score=0.98,
        )
    ]

    raw, cits = parse_citations(
        "Antigravity is an AI IDE.\n\nCITATIONS:\n[1] guide.txt, chunk 0", mock_chunks
    )
    assert "Antigravity is an AI IDE." in raw
    assert len(cits) == 1
    assert cits[0]["document_name"] == "guide.txt"

    # Citation parsing without citations block
    raw, cits = parse_citations("Plain response without citations", mock_chunks)
    assert raw == "Plain response without citations"
    assert cits == []

    # Out-of-range citation indices are dropped, not invented.
    raw, cits = parse_citations("Answer.\n\nCITATIONS:\n[9] nope.txt, chunk 3", mock_chunks)
    assert cits == []


@pytest.mark.asyncio
async def test_agent_service_nodes() -> None:
    owner_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())

    # Planner node normal
    mock_plan_resp = MagicMock()
    mock_plan_choice = MagicMock()
    mock_plan_choice.message.content = '{"needs_retrieval": true, "retrieval_query": "What is Python?"}'
    mock_plan_resp.choices = [mock_plan_choice]

    with patch("app.services.agent_service.get_openai_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_plan_resp)
        mock_get_client.return_value = mock_client

        state = {
            "question": "What is it?",
            "owner_id": owner_id,
            "document_id": doc_id,
            "history": [{"role": "user", "content": "Tell me about Python."}],
            "retrieval_query": "",
            "chunks": [],
            "answer": "",
            "citations": [],
            "needs_retrieval": False,
        }
        res_planner = await planner_node(state)
        assert res_planner["needs_retrieval"] is True
        assert res_planner["retrieval_query"] == "What is Python?"

    # Planner node error fallback
    with patch("app.services.agent_service.get_openai_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("LLM planner error"))
        mock_get_client.return_value = mock_client

        res_planner_err = await planner_node(state)
        assert res_planner_err["needs_retrieval"] is True
        assert res_planner_err["retrieval_query"] == "What is it?"

    # Retriever node
    mock_chunks = [
        RetrievedChunk(text="Python info", document_id=doc_id, document_name="doc.txt", chunk_index=0, score=0.9)
    ]
    with (
        patch("app.services.embedding_service.EmbeddingService.embed_text", new_callable=AsyncMock, return_value=[0.1]*3072),
        patch("app.services.vector_store_service.VectorStoreService.search", new_callable=AsyncMock, return_value=mock_chunks),
    ):
        res_retriever = await retriever_node(res_planner)
        assert len(res_retriever["chunks"]) == 1

    # Reasoning node normal
    mock_reasoning_resp = MagicMock()
    mock_r_choice = MagicMock()
    mock_r_choice.message.content = "Python is a language.\n\nCITATIONS:\n[1] doc.txt, chunk 0"
    mock_reasoning_resp.choices = [mock_r_choice]

    with patch("app.services.agent_service.get_openai_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_reasoning_resp)
        mock_get_client.return_value = mock_client

        res_reasoning = await reasoning_node(res_retriever)
        assert "Python is a language." in res_reasoning["answer"]

    # Reasoning node empty chunks
    res_empty_chunks = await reasoning_node({**res_retriever, "chunks": []})
    assert "couldn't find" in res_empty_chunks["answer"]

    # Phase A: reasoning node no longer hides LLM failures behind a
    # snippet fallback; it raises AgentError for the router to map to 502.
    with patch("app.services.agent_service.get_openai_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("LLM reasoning error"))
        mock_get_client.return_value = mock_client

        with pytest.raises(AgentError):
            await reasoning_node(res_retriever)

    # Response node
    res_response = await response_node(res_reasoning)
    assert len(res_response["citations"]) == 1

    # Routing condition (Phase A: skip now goes to the direct-answer node,
    # not to reasoning with empty chunks)
    assert should_retrieve({"needs_retrieval": True}) == "retriever"
    assert should_retrieve({"needs_retrieval": False}) == "direct"

    # Direct-answer node answers without documents or citations.
    mock_direct_resp = MagicMock()
    mock_direct_choice = MagicMock()
    mock_direct_choice.message.content = "Hello! How can I help?"
    mock_direct_resp.choices = [mock_direct_choice]
    with patch("app.services.agent_service.get_openai_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_direct_resp)
        mock_get_client.return_value = mock_client
        res_direct = await direct_answer_node({**res_retriever, "chunks": []})
        assert "Hello!" in res_direct["answer"]
        assert res_direct["citations"] == []

    # Full AgentService run
    agent = AgentService()
    with patch.object(agent, "run", new_callable=AsyncMock, return_value=RagAnswer(answer="Final answer", citations=[])):
        ans = await agent.run("Query", uuid.UUID(owner_id))
        assert ans.answer == "Final answer"
