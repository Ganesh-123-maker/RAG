from __future__ import annotations

import json
import logging
import uuid
from typing import TypedDict

from langgraph.graph import END, StateGraph
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.embedding_service import EmbeddingService, get_openai_client
from app.services.rag_service import RagAnswer, RagService
from app.services.vector_store_service import RetrievedChunk, VectorStoreService

settings = get_settings()
logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    question: str
    owner_id: str
    document_id: str | None
    history: list[dict]
    retrieval_query: str
    chunks: list[dict]
    answer: str
    citations: list[dict]
    needs_retrieval: bool


async def planner_node(state: AgentState) -> dict:
    llm: AsyncOpenAI = get_openai_client()

    history_summary = ""
    if state["history"]:
        last_msgs = state["history"][-4:]
        history_summary = "\n".join(
            f"{m['role'].upper()}: {str(m['content'])[:200]}" for m in last_msgs
        )

    planner_prompt = (
        f"You are a query planner for a RAG system.\n\n"
        f"Conversation history (last 2 turns):\n{history_summary or 'None'}\n\n"
        f"Current question: {state['question']}\n\n"
        f"Tasks:\n"
        f"1. Decide if document retrieval is needed (true/false).\n"
        f"   Say false ONLY for greetings or simple math with no document context.\n"
        f"2. If true, write a self-contained retrieval query (no pronouns, standalone).\n\n"
        f'Respond in JSON exactly:\n{{"needs_retrieval": true, "retrieval_query": "..."}}\n'
        f'or\n{{"needs_retrieval": false, "retrieval_query": ""}}'
    )

    try:
        response = await llm.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=[{"role": "user", "content": planner_prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        plan: dict = json.loads(response.choices[0].message.content or "{}")
    except Exception as exc:
        logger.warning("Planner LLM call failed, defaulting to retrieval: %s", exc)
        plan = {"needs_retrieval": True, "retrieval_query": state["question"]}

    return {
        **state,
        "needs_retrieval": bool(plan.get("needs_retrieval", True)),
        "retrieval_query": plan.get("retrieval_query") or state["question"],
    }


async def retriever_node(state: AgentState) -> dict:
    embed_svc = EmbeddingService()
    vector_svc = VectorStoreService()

    query_vector = await embed_svc.embed_text(state["retrieval_query"])
    doc_id = uuid.UUID(state["document_id"]) if state.get("document_id") else None

    chunks: list[RetrievedChunk] = await vector_svc.search(
        query_vector=query_vector,
        owner_id=uuid.UUID(state["owner_id"]),
        document_id=doc_id,
    )
    logger.debug("Retrieved %d chunks for query: %s", len(chunks), state["retrieval_query"][:60])

    return {
        **state,
        "chunks": [
            {
                "text": c.text,
                "document_id": c.document_id,
                "document_name": c.document_name,
                "chunk_index": c.chunk_index,
                "score": c.score,
            }
            for c in chunks
        ],
    }


async def reasoning_node(state: AgentState) -> dict:
    llm: AsyncOpenAI = get_openai_client()
    chunks = state["chunks"]

    if not chunks:
        return {
            **state,
            "answer": "I couldn't find relevant information in your documents.",
            "citations": [],
        }

    context_parts = [
        f"[{i}] From '{c['document_name']}' (chunk {c['chunk_index']}):\n{c['text']}"
        for i, c in enumerate(chunks, 1)
    ]
    context_block = "\n\n---\n\n".join(context_parts)

    system_msg = {
        "role": "system",
        "content": (
            "You are a precise research assistant. Answer using ONLY the provided context. "
            "End your response with:\n\nCITATIONS:\n[1] document_name, chunk N\n[2] ..."
        ),
    }
    user_msg = {
        "role": "user",
        "content": f"Context:\n{context_block}\n\nQuestion: {state['question']}",
    }

    recent_history = (state["history"] or [])[-10:]
    messages = [system_msg, *recent_history, user_msg]

    response = await llm.chat.completions.create(
        model=settings.OPENAI_CHAT_MODEL,
        messages=messages,
        temperature=0.1,
    )
    return {**state, "answer": response.choices[0].message.content or ""}


async def response_node(state: AgentState) -> dict:
    chunks = [
        RetrievedChunk(
            text=c["text"],
            document_id=c["document_id"],
            document_name=c["document_name"],
            chunk_index=c["chunk_index"],
            score=c["score"],
        )
        for c in state["chunks"]
    ]
    answer_text, citations = RagService._parse_citations(state["answer"], chunks)
    return {**state, "answer": answer_text, "citations": citations}


def should_retrieve(state: AgentState) -> str:
    return "retriever" if state.get("needs_retrieval", True) else "reasoning"


def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("planner", planner_node)
    g.add_node("retriever", retriever_node)
    g.add_node("reasoning", reasoning_node)
    g.add_node("response", response_node)
    g.set_entry_point("planner")
    g.add_conditional_edges("planner", should_retrieve)
    g.add_edge("retriever", "reasoning")
    g.add_edge("reasoning", "response")
    g.add_edge("response", END)
    return g.compile()


_agent_graph = _build_graph()


class AgentService:
    async def run(
        self,
        question: str,
        owner_id: uuid.UUID,
        history: list[dict] | None = None,
        document_id: uuid.UUID | None = None,
    ) -> RagAnswer:
        initial_state: AgentState = {
            "question": question,
            "owner_id": str(owner_id),
            "document_id": str(document_id) if document_id else None,
            "history": history or [],
            "retrieval_query": question,
            "chunks": [],
            "answer": "",
            "citations": [],
            "needs_retrieval": True,
        }
        logger.info("Agent run started for owner=%s question=%s", owner_id, question[:60])
        final_state = await _agent_graph.ainvoke(initial_state)
        logger.info(
            "Agent run complete: %d citations, answer_len=%d",
            len(final_state["citations"]),
            len(final_state["answer"]),
        )
        return RagAnswer(
            answer=final_state["answer"],
            citations=final_state["citations"],
        )
