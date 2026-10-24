from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import configure_logging, get_settings
from app.core.database import engine
from app.routers import auth, chat, documents
from app.services.vector_store_service import VectorStoreService

settings = get_settings()
configure_logging("DEBUG" if settings.ENVIRONMENT == "development" else "INFO")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Schema is created by Alembic migrations (see backend/entrypoint.sh),
    # NOT by create_all() here: create_all() silently diverges from the
    # migration history and masked schema drift in Phase A review.
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory ready: %s", upload_dir.resolve())

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


async def _check_database() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_qdrant() -> None:
    vs = VectorStoreService()
    await vs._client.get_collections()


@app.get("/health")
async def health() -> dict:
    """Liveness only: the process is up. Use /ready for dependencies."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/ready")
async def ready() -> JSONResponse:
    """Readiness: Postgres and Qdrant must both answer within 5s."""
    failures: list[str] = []
    try:
        await asyncio.wait_for(_check_database(), timeout=5)
    except Exception as exc:  # noqa: BLE001 -- any dep failure means not-ready
        logger.warning("Readiness: database check failed: %s", exc)
        failures.append("database")
    try:
        await asyncio.wait_for(_check_qdrant(), timeout=5)
    except Exception as exc:  # noqa: BLE001 -- any dep failure means not-ready
        logger.warning("Readiness: qdrant check failed: %s", exc)
        failures.append("qdrant")
    if failures:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "failures": failures},
        )
    return JSONResponse(content={"status": "ready", "version": "1.0.0"})
