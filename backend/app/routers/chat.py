from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.chat import (
    ChatRequest,
    CitationSchema,
    ConversationListResponse,
    ConversationResponse,
    MessageResponse,
)
from app.services.agent_service import AgentService

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/", response_model=MessageResponse, status_code=201)
async def chat(
    payload: ChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    conv_repo = ConversationRepository(db)

    if payload.conversation_id:
        conv = await conv_repo.get_conversation(payload.conversation_id, current_user.id)
        if conv is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    else:
        title = payload.question[:50] + ("..." if len(payload.question) > 50 else "")
        conv = await conv_repo.create_conversation(current_user.id, title=title)

    existing_messages = await conv_repo.get_messages(conv.id)
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in existing_messages
    ]

    await conv_repo.add_message(
        conversation_id=conv.id,
        role="user",
        content=payload.question,
    )

    agent = AgentService()
    result = await agent.run(
        question=payload.question,
        owner_id=current_user.id,
        history=history,
        document_id=payload.document_id,
    )

    citations_json = json.dumps(result.citations)
    assistant_msg = await conv_repo.add_message(
        conversation_id=conv.id,
        role="assistant",
        content=result.answer,
        citations_json=citations_json,
    )

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    messages = []
    for msg in conv.messages:
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


@router.delete("/conversations/{conversation_id}", status_code=204, response_class=Response)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_conversation(conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    await conv_repo.delete_conversation(conversation_id)
    logger.info("Deleted conversation %s for user %s", conversation_id, current_user.id)
    return Response(status_code=204)


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    from app.core.database import AsyncSessionLocal
    from app.core.config import get_settings
    from app.services.embedding_service import EmbeddingService, get_openai_client
    from app.services.vector_store_service import VectorStoreService

    settings = get_settings()
    conv_repo = ConversationRepository(db)

    conv_id = payload.conversation_id
    if conv_id:
        conv = await conv_repo.get_conversation(conv_id, current_user.id)
        if conv is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    else:
        title = payload.question[:50] + ("..." if len(payload.question) > 50 else "")
        conv = await conv_repo.create_conversation(current_user.id, title=title)
        conv_id = conv.id

    existing = await conv_repo.get_messages(conv_id)
    history = [{"role": m.role, "content": m.content} for m in existing[-10:]]
    await conv_repo.add_message(conv_id, "user", payload.question)

    embed_svc = EmbeddingService()
    vector_svc = VectorStoreService()
    query_vector = await embed_svc.embed_text(payload.question)
    chunks = await vector_svc.search(
        query_vector=query_vector,
        owner_id=current_user.id,
        document_id=payload.document_id,
    )

    # Build citations list from retrieved chunks — will be saved with the message after streaming
    stream_citations = [
        {
            "document_id": c.document_id,
            "document_name": c.document_name,
            "chunk_index": c.chunk_index,
            "score": round(c.score, 4),
            "snippet": c.text[:200] + "..." if len(c.text) > 200 else c.text,
        }
        for c in chunks
    ]

    context_block = "\n\n---\n\n".join(
        f"[{i+1}] From '{c.document_name}':\n{c.text}" for i, c in enumerate(chunks)
    )

    messages = [
        {"role": "system", "content": "Answer using the provided context. Be concise and cite sources."},
        *history,
        {"role": "user", "content": f"Context:\n{context_block}\n\nQuestion: {payload.question}"},
    ]

    async def event_stream() -> AsyncGenerator[str, None]:
        llm = get_openai_client()
        full_response = ""
        try:
            stream = await llm.chat.completions.create(
                model=settings.OPENAI_CHAT_MODEL,
                messages=messages,
                temperature=0.1,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as exc:
            logger.error("Stream error: %s", exc)
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

        # Persist assistant message with citations so conversation reload shows sources
        citations_json = json.dumps(stream_citations)
        async with AsyncSessionLocal() as session:
            repo = ConversationRepository(session)
            await repo.add_message(conv_id, "assistant", full_response, citations_json=citations_json)
            await session.commit()

        yield f"data: {json.dumps({'done': True, 'conversation_id': str(conv_id)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
