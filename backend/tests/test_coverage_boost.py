from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.routers.auth import me as auth_me_endpoint
from app.routers.auth import register as auth_register_endpoint
from app.routers.chat import (
    chat as chat_endpoint,
)
from app.routers.chat import (
    delete_conversation as delete_conv_endpoint,
)
from app.routers.chat import (
    get_conversation as get_conv_endpoint,
)
from app.routers.chat import (
    list_conversations as list_convs_endpoint,
)
from app.routers.documents import (
    delete_document as delete_doc_endpoint,
)
from app.routers.documents import (
    get_document as get_doc_endpoint,
)
from app.routers.documents import (
    list_documents as list_docs_endpoint,
)
from app.routers.documents import (
    upload_document as upload_doc_endpoint,
)
from app.schemas.auth import RegisterRequest
from app.schemas.chat import ChatRequest
from app.services.rag_service import RagAnswer


@pytest.mark.asyncio
async def test_database_get_db_rollback(db_session: AsyncSession) -> None:
    gen = get_db()
    _session = await anext(gen)
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("DB Error"))


@pytest.mark.asyncio
async def test_direct_router_function_coverage(
    db_session: AsyncSession, fake_user: User
) -> None:
    # 1. Documents router direct
    fake_file = UploadFile(
        filename="direct.txt", file=io.BytesIO(b"Direct test document content")
    )
    with (
        patch(
            "app.services.document_service.EmbeddingService.embed_batch",
            new_callable=AsyncMock,
            return_value=[[0.1] * 3072],
        ),
        patch(
            "app.services.document_service.VectorStoreService.upsert_chunks",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.document_service.VectorStoreService.ensure_collection",
            new_callable=AsyncMock,
        ),
    ):
        doc_resp = await upload_doc_endpoint(
            file=fake_file, current_user=fake_user, db=db_session
        )
        assert doc_resp.original_name == "direct.txt"

    # List documents
    docs_list = await list_docs_endpoint(current_user=fake_user, db=db_session)
    assert docs_list.total >= 1

    # Get document
    doc_get = await get_doc_endpoint(
        document_id=doc_resp.id, current_user=fake_user, db=db_session
    )
    assert doc_get.id == doc_resp.id

    # Delete document
    with patch(
        "app.services.document_service.VectorStoreService.delete_by_document",
        new_callable=AsyncMock,
    ):
        del_resp = await delete_doc_endpoint(
            document_id=doc_resp.id, current_user=fake_user, db=db_session
        )
        assert del_resp.status_code == 204

    # 2. Chat router direct
    mock_rag_result = RagAnswer(
        answer="Direct chat answer",
        citations=[
            {
                "document_id": str(uuid.uuid4()),
                "document_name": "src.txt",
                "chunk_index": 0,
                "score": 0.95,
                "snippet": "...",
            }
        ],
    )

    with patch(
        "app.routers.chat.AgentService.run",
        new_callable=AsyncMock,
        return_value=mock_rag_result,
    ):
        # Chat without conv_id
        chat_res1 = await chat_endpoint(
            payload=ChatRequest(question="Question 1"),
            current_user=fake_user,
            db=db_session,
        )
        assert chat_res1.content == "Direct chat answer"
        assert len(chat_res1.citations) == 1

        # List conversations
        convs = await list_convs_endpoint(current_user=fake_user, db=db_session)
        assert len(convs.conversations) >= 1
        conv_id = convs.conversations[0].id

        # Chat with existing conv_id
        chat_res2 = await chat_endpoint(
            payload=ChatRequest(question="Question 2", conversation_id=conv_id),
            current_user=fake_user,
            db=db_session,
        )
        assert chat_res2.content == "Direct chat answer"

        # Get conversation
        conv_detail = await get_conv_endpoint(
            conversation_id=conv_id, current_user=fake_user, db=db_session
        )
        assert len(conv_detail.messages) >= 2

        # Delete conversation
        del_conv_res = await delete_conv_endpoint(
            conversation_id=conv_id, current_user=fake_user, db=db_session
        )
        assert del_conv_res.status_code == 204

    # 3. Auth router direct
    user_resp = await auth_me_endpoint(current_user=fake_user)
    assert user_resp.email == fake_user.email

    reg_user = await auth_register_endpoint(
        payload=RegisterRequest(
            email="direct_reg@example.com",
            password="pass1234password",
            full_name="Direct Reg",
        ),
        db=db_session,
    )
    assert reg_user.email == "direct_reg@example.com"
