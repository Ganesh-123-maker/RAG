from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.core.config import configure_logging, get_settings
from app.core.database import engine
from app.core.observability import RequestIDMetricsMiddleware, metrics
from app.routers import auth, chat, documents
from app.services.embedding_service import get_openai_client
from app.services.vector_store_service import (
    VectorStoreService,
    get_qdrant_client,
)

settings = get_settings()
configure_logging("DEBUG" if settings.ENVIRONMENT == "development" else "INFO")

logger = logging.getLogger(__name__)

# Sentry is optional and env-gated (Phase E): no DSN means no-op.
# Import failure is also a no-op, never a boot failure.
if settings.SENTRY_DSN:
    try:
        import sentry_sdk  # type: ignore[import-not-found]

        sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1)
        logger.info("Sentry error tracking enabled (DSN configured).")
    except Exception as exc:  # noqa: BLE001 -- Sentry must never break boot
        logger.warning("Sentry DSN set but SDK init failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Schema is created by Alembic migrations (see backend/entrypoint.sh),
    # NOT by create_all() here: create_all() silently diverges from the
    # migration history and masked schema drift in Phase A review.
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory ready: %s", upload_dir.resolve())

    # Phase E startup checks: an OpenAI key is required outside tests
    # (embedding/chat cannot work without it, and failing at boot is
    # honest whereas failing at first user request is not). The
    # collection-dimension check lives in ensure_collection(), which
    # raises CollectionDimensionMismatchError on mismatch.
    if (
        settings.ENVIRONMENT or "development"
    ).lower() != "test" and not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY must be set (except in ENVIRONMENT=test)")
    vs = VectorStoreService()
    await vs.ensure_collection()
    logger.info("Vector store collection ready: %s", settings.QDRANT_COLLECTION)

    yield

    # Graceful shutdown: close clients that support it. The OpenAI
    # and Qdrant async clients are module singletons; closing them
    # is best-effort and must not mask shutdown errors.
    try:
        await get_openai_client().close()
    except Exception:  # noqa: BLE001, S110 -- best-effort shutdown
        pass
    try:
        await get_qdrant_client().close()
    except Exception:  # noqa: BLE001, S110 -- best-effort shutdown
        pass
    try:
        await engine.dispose()
    except Exception:  # noqa: BLE001, S110 -- best-effort shutdown
        pass
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

# Added last so it runs outermost (Starlette middleware runs in
# reverse addition order): every request, including CORS preflights
# and errors, gets a request ID, a JSON log line, and a metric.
app.add_middleware(RequestIDMetricsMiddleware)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")


async def _check_database() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_qdrant() -> None:
    vs = VectorStoreService()
    await vs._client.get_collections()


@app.get("/metrics")
async def metrics_endpoint() -> PlainTextResponse:
    """Minimal Prometheus-text metrics (Phase E).

    This is NOT a prometheus_client integration: counters and
    latency histograms are kept in-process and rendered as
    Prometheus text format. Per-process, lost on restart.
    """
    return PlainTextResponse(content=metrics.render(), media_type="text/plain")


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
