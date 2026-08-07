from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import configure_logging, get_settings
from app.routers import auth, chat, documents
from app.services.vector_store_service import VectorStoreService

settings = get_settings()
configure_logging("DEBUG" if settings.ENVIRONMENT == "development" else "INFO")

import logging
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from app.core.database import engine, Base
    from app.models.user import User  # noqa: F401
    from app.models.document import Document  # noqa: F401
    from app.models.conversation import Conversation, Message  # noqa: F401

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory ready: %s", upload_dir.resolve())

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified/created")
    except Exception as exc:
        logger.warning("Database table creation deferred: %s", exc)

    vs = VectorStoreService()
    await vs.ensure_collection()
    logger.info("Vector store collection ready: %s", settings.QDRANT_COLLECTION)

    yield

    logger.info("Application shutdown complete")


app = FastAPI(
    title="Agentic RAG Knowledge Assistant",
    description="Upload documents, ask questions, get cited answers powered by GPT-4o + Qdrant.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}
