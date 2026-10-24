from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import database as db_module
from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import CurrentUser
from app.core.quotas import check_daily_quota, estimate_tokens, record_daily_usage
from app.core.rate_limit import check_rate_limit
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.chat import (
    ChatRequest,
    CitationSchema,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdate,
    MessageResponse,
)
from app.services.agent_service import AgentService
from app.services.rag_service import parse_citations

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


async def _resolve_conversation(
    conv_repo: ConversationRepository,
    payload: ChatRequest,
    owner_id: uuid.UUID,
):
    if payload.conversation_id:
        conv = await conv_repo.get_conversation(payload.conversation_id, owner_id)
        if conv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
        return conv
    title = payload.question[:50] + ("..." if len(payload.question) > 50 else "")
    return await conv_repo.create_conversation(owner_id, title=title)


async def _check_document(
    db: AsyncSession, document_id: uuid.UUID | None, owner_id: uuid.UUID
) -> None:
    """Ownership + readiness check for document-scoped chat.

    404 for another user's (or missing) document, 409 for a document that
    exists but is not ready yet. Without this, a non-ready document would
    silently search an empty vector set.
    """
    if document_id is None:
        return
    repo = DocumentRepository(db)
    doc = await repo.get_by_id_for_owner(document_id, owner_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    if doc.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is not ready yet",
        )


@router.post("", response_model=MessageResponse, status_code=201)
@router.post(
    "/", response_model=MessageResponse, status_code=201, include_in_schema=False
)
async def chat(
    payload: ChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    settings = get_settings()
    check_rate_limit(f"chat:{current_user.id}", settings.CHAT_RATE_LIMIT_PER_MINUTE, 60)
    check_daily_quota(current_user.id)
    conv_repo = ConversationRepository(db)
    conv = await _resolve_conversation(conv_repo, payload, current_user.id)
    await _check_document(db, payload.document_id, current_user.id)

    existing_messages = await conv_repo.get_messages_for_owner(conv.id, current_user.id)
    history = [{"role": msg.role, "content": msg.content} for msg in existing_messages]

    await conv_repo.add_message(
        conversation_id=conv.id,
        role="user",
        content=payload.question,
    )

    agent = AgentService()
    try:
        result = await agent.run(
            question=payload.question,
            owner_id=current_user.id,
            history=history,
            document_id=payload.document_id,
        )
    except Exception as exc:
        logger.error("Agent run failed for conversation %s", conv.id, exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Chat service is temporarily unavailable.",
        ) from exc

    record_daily_usage(
        current_user.id,
        estimate_tokens(payload.question) + estimate_tokens(result.answer),
    )
    citations_json = json.dumps(result.citations)
    assistant_msg = await conv_repo.add_message(
        conversation_id=conv.id,
        role="assistant",
        content=result.answer,
        citations_json=citations_json,
    )
    await db.commit()

    return MessageResponse(
        id=assistant_msg.id,
        role="assistant",
        content=result.answer,
        citations=[CitationSchema(**c) for c in result.citations],
        created_at=assistant_msg.created_at,
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    conv_repo = ConversationRepository(db)
    convs = await conv_repo.list_conversations(current_user.id)
    return ConversationListResponse(
        conversations=[
            ConversationResponse(
                id=c.id,
                title=c.title,
                created_at=c.created_at,
            )
            for c in convs
        ]
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_conversation(conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )

    msgs = await conv_repo.get_messages_for_owner(conversation_id, current_user.id)
    messages = []
    for msg in msgs:
        raw_citations = json.loads(msg.citations_json) if msg.citations_json else []
        messages.append(
            MessageResponse(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                citations=[CitationSchema(**c) for c in raw_citations],
                created_at=msg.created_at,
            )
        )
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        messages=messages,
    )


@router.patch(
    "/conversations/{conversation_id}", response_model=ConversationResponse
)
async def rename_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Phase F: owner-scoped rename. Another user's conversation
    is indistinguishable from a missing one (404)."""
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.update_title_for_owner(
        conversation_id, current_user.id, payload.title
    )
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return ConversationResponse(
        id=conv.id, title=conv.title, created_at=conv.created_at, messages=[]
    )


@router.delete(
    "/conversations/{conversation_id}", status_code=204, response_class=Response
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    conv_repo = ConversationRepository(db)
    deleted = await conv_repo.delete_conversation_for_owner(
        conversation_id, current_user.id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    logger.info("Deleted conversation %s for user %s", conversation_id, current_user.id)
    return Response(status_code=204)


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Streaming chat through the SAME LangGraph service as /chat.

    SSE event shapes (all ``data: {...}\\n\\n``):
    ``status`` ({"status": "started"}), ``token`` ({"token": ...}),
    ``citations`` ({"citations": [...]}), ``done``
    ({"done": true, "conversation_id": ..., "answer": ..., "citations": [...]}),
    ``error`` ({"error": <safe message>}).
    The assistant message is persisted in the generator's ``finally`` block,
    so it is saved even if the client disconnects mid-stream (with whatever
    was streamed so far) instead of being lost.
    """
    settings = get_settings()
    check_rate_limit(f"chat:{current_user.id}", settings.CHAT_RATE_LIMIT_PER_MINUTE, 60)
    check_daily_quota(current_user.id)
    conv_repo = ConversationRepository(db)
    conv = await _resolve_conversation(conv_repo, payload, current_user.id)
    conv_id = conv.id
    await _check_document(db, payload.document_id, current_user.id)

    existing = await conv_repo.get_messages_for_owner(conv_id, current_user.id)
    history = [{"role": m.role, "content": m.content} for m in existing]
    await conv_repo.add_message(conv_id, "user", payload.question)

    agent = AgentService()

    async def event_stream() -> AsyncGenerator[str, None]:
        accumulated = ""
        final_answer: str | None = None
        citations: list[dict] = []
        persisted = False

        async def persist() -> None:
            nonlocal persisted
            if persisted:
                return
            persisted = True
            answer = (
                final_answer
                if final_answer is not None
                else parse_citations(accumulated, [])[0]
            )
            async with db_module.AsyncSessionLocal() as session:
                repo = ConversationRepository(session)
                await repo.add_message(
                    conv_id, "assistant", answer, citations_json=json.dumps(citations)
                )
                await session.commit()

        try:
            async for event in agent.run_stream(
                question=payload.question,
                owner_id=current_user.id,
                history=history,
                document_id=payload.document_id,
            ):
                if event["type"] == "status":
                    yield f"data: {json.dumps({'status': event['status']})}\n\n"
                elif event["type"] == "token":
                    accumulated += event["token"]
                    yield f"data: {json.dumps({'token': event['token']})}\n\n"
                elif event["type"] == "citations":
                    citations = event["citations"]
                    yield f"data: {json.dumps({'citations': citations})}\n\n"
                elif event["type"] == "done":
                    final_answer = event["answer"]
                    citations = event["citations"]
                    done_payload = {
                        "done": True,
                        "conversation_id": str(conv_id),
                        "answer": final_answer,
                        "citations": citations,
                    }
                    yield f"data: {json.dumps(done_payload)}\n\n"
                elif event["type"] == "error":
                    yield f"data: {json.dumps({'error': event['detail']})}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            # Client disconnected: do not yield (illegal here); persist in finally.
            raise
        except Exception as exc:
            logger.error("Stream failed for conversation %s", conv_id, exc_info=exc)
            yield f"data: {json.dumps({'error': 'Chat service is temporarily unavailable.'})}\n\n"
        finally:
            try:
                await persist()
            except Exception as exc:
                logger.error(
                    "Failed to persist streamed answer for %s", conv_id, exc_info=exc
                )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
