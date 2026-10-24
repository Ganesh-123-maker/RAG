from __future__ import annotations

import io
import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import quotas
from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.core.config import Settings
from app.core.rate_limit import InMemoryRateLimiter, limiter
from app.core.token_denylist import clear as clear_denylist
from app.main import app
from app.repositories.document_repository import DocumentRepository
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService
from app.services.vector_store_service import VectorStoreService
from scripts.reconcile_orphans import find_orphan_files, find_orphan_vector_doc_ids


@pytest.fixture(autouse=True)
def _enable_limiter():
    """Rate limiter is off by default in test env; enable it here only."""
    limiter.set_enabled_for_tests(True)
    limiter.clear()
    quotas.clear()
    clear_denylist()
    yield
    limiter.set_enabled_for_tests(False)
    limiter.clear()
    quotas.clear()
    clear_denylist()


def test_rate_limiter_429_and_retry_after() -> None:
    rl = InMemoryRateLimiter()
    rl.set_enabled_for_tests(True)
    rl.check("k", 2, 60)
    rl.check("k", 2, 60)
    with pytest.raises(Exception) as exc_info:
        rl.check("k", 2, 60)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.asyncio
async def test_upload_rate_limit_429(test_client: AsyncClient) -> None:
    txt = b"Rate limit test document with enough content for a chunk."
    with (
        patch(
            "app.services.embedding_service.EmbeddingService.embed_batch",
            new_callable=AsyncMock,
            return_value=[[0.1] * 3072],
        ),
        patch(
            "app.services.vector_store_service.VectorStoreService.upsert_chunks",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.vector_store_service.VectorStoreService.ensure_collection",
            new_callable=AsyncMock,
        ),
    ):
        statuses = []
        for _ in range(11):
            resp = await test_client.post(
                "/api/v1/documents/upload",
                files={"file": ("test.txt", io.BytesIO(txt), "text/plain")},
            )
            statuses.append(resp.status_code)
    assert statuses[-1] == 429
    assert "Retry-After" in resp.headers


@pytest.mark.asyncio
async def test_lockout_after_failed_logins(db_session: AsyncSession) -> None:
    svc = AuthService(db_session)
    await svc.register(
        SimpleNamespace(
            email="locked@example.com", password="securepass123", full_name="Locked"
        )
    )
    for _ in range(5):
        with pytest.raises(Exception) as exc_info:
            await svc.login("locked@example.com", "wrongpassword")
        assert exc_info.value.status_code == 401
    # Correct password is now refused while locked.
    with pytest.raises(Exception) as exc_info:
        await svc.login("locked@example.com", "securepass123")
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.asyncio
async def test_login_sets_httpony_cookie_and_logout_revokes(
    db_session: AsyncSession,
) -> None:
    from app.core.database import get_db
    from app.core.dependencies import get_current_user

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # The conftest fake user has a non-verifiable placeholder
            # hash, so register a real user first.
            reg = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "cookie@example.com",
                    "password": "securepass123",
                    "full_name": "Cookie",
                },
            )
            assert reg.status_code == 201
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "cookie@example.com", "password": "securepass123"},
            )
            assert resp.status_code == 200
            set_cookie = resp.headers.get("set-cookie", "")
            assert "HttpOnly" in set_cookie
            assert "SameSite=lax" in set_cookie
            # max_age matches the 60-minute JWT lifetime exactly.
            assert "Max-Age=3600" in set_cookie
            assert "Secure" not in set_cookie  # not production in tests
            me = await client.get("/api/v1/auth/me")
            assert me.status_code == 200
            out = await client.post("/api/v1/auth/logout")
            assert out.status_code == 200
            # The revoked token no longer authenticates, even with the
            # cookie still present in the client jar.
            me2 = await client.get("/api/v1/auth/me")
            assert me2.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_request_id_header_and_metrics(test_client: AsyncClient) -> None:
    resp = await test_client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("x-request-id")
    metrics_resp = await test_client.get("/metrics")
    assert metrics_resp.status_code == 200
    assert "rag_http_requests_total" in metrics_resp.text
    assert "rag_http_request_duration_seconds" in metrics_resp.text


def test_cors_wildcard_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            ENVIRONMENT="production",
            OPENAI_API_KEY="x",
            JWT_SECRET_KEY="y" * 32,
            BACKEND_CORS_ORIGINS=["*"],
        )


def test_production_requires_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="production", OPENAI_API_KEY="x", JWT_SECRET_KEY=None)


def test_top_k_must_not_exceed_fetch_k() -> None:
    with pytest.raises(ValidationError):
        Settings(
            OPENAI_API_KEY="x",
            JWT_SECRET_KEY="y" * 32,
            RETRIEVAL_TOP_K=25,
            RETRIEVAL_FETCH_K=20,
        )


def test_circuit_breaker_opens_and_recovers() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    breaker.before_call()
    breaker.on_failure()
    breaker.before_call()
    breaker.on_failure()
    with pytest.raises(CircuitOpenError):
        breaker.before_call()
    # Simulate cooldown expiry: half-open trial succeeds -> closed.
    import time as _time

    breaker._opened_at = _time.monotonic() - 61
    breaker.before_call()
    breaker.on_success()
    breaker.before_call()  # closed again, no exception


@pytest.mark.asyncio
async def test_qdrant_search_circuit_breaker_opens() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    svc = VectorStoreService(breaker=breaker)
    failing = AsyncMock(side_effect=RuntimeError("qdrant down"))
    svc._client.search = failing  # type: ignore[attr-defined]
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await svc.search([0.1] * 3072, uuid.uuid4())
    assert failing.call_count == 2
    with pytest.raises(CircuitOpenError):
        await svc.search([0.1] * 3072, uuid.uuid4())
    assert failing.call_count == 2  # fail-fast, no third call


def test_daily_quota_enforced() -> None:
    settings = SimpleNamespace(
        ENVIRONMENT="development", DAILY_CHAT_REQUESTS=2, DAILY_TOKEN_BUDGET_EST=100
    )
    user = uuid.uuid4()
    quotas.check_daily_quota(user, settings=settings)
    quotas.record_daily_usage(user, 10)
    quotas.check_daily_quota(user, settings=settings)
    quotas.record_daily_usage(user, 10)
    with pytest.raises(Exception) as exc_info:
        quotas.check_daily_quota(user, settings=settings)
    assert exc_info.value.status_code == 429


def test_reconcile_pure_functions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "keep.txt").write_bytes(b"keep")
    (tmp_path / "orphan.txt").write_bytes(b"orphan")
    orphans = find_orphan_files(tmp_path, {"keep.txt"})
    assert [p.name for p in orphans] == ["orphan.txt"]
    assert find_orphan_vector_doc_ids({"a", "b"}, {"a"}) == {"b"}


@pytest.mark.asyncio
async def test_ingestion_queue_status_and_worker(
    db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    import app.services.document_service as doc_mod

    monkeypatch.setattr(doc_mod.settings, "UPLOAD_DIR", str(tmp_path))
    owner = uuid.uuid4()
    repo = DocumentRepository(db_session)
    doc = await repo.create(
        owner_id=owner,
        filename="queued.txt",
        original_name="queued.txt",
        file_type="txt",
        file_size_bytes=50,
        status="queued",
    )
    upload_dir = tmp_path / str(owner)
    upload_dir.mkdir(parents=True)
    (upload_dir / "queued.txt").write_bytes(
        b"This queued document has enough content to chunk and index."
    )
    svc = DocumentService(db_session)
    with (
        patch(
            "app.services.embedding_service.EmbeddingService.embed_batch",
            new_callable=AsyncMock,
            return_value=[[0.1] * 3072],
        ),
        patch(
            "app.services.vector_store_service.VectorStoreService.upsert_chunks",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.vector_store_service.VectorStoreService.ensure_collection",
            new_callable=AsyncMock,
        ),
    ):
        result = await svc.process_queued_documents()
    assert result == {"processed": 1, "errored": 0, "total": 1}
    finished = await repo.get_by_id_for_owner(doc.id, owner)
    assert finished is not None
    assert finished.status == "ready"
    assert finished.ingestion_progress == 100
    assert finished.ingestion_attempts == 1


@pytest.mark.asyncio
async def test_upload_response_carries_progress(test_client: AsyncClient) -> None:
    txt = b"Progress test document with enough content for a chunk."
    with (
        patch(
            "app.services.embedding_service.EmbeddingService.embed_batch",
            new_callable=AsyncMock,
            return_value=[[0.1] * 3072],
        ),
        patch(
            "app.services.vector_store_service.VectorStoreService.upsert_chunks",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.vector_store_service.VectorStoreService.ensure_collection",
            new_callable=AsyncMock,
        ),
    ):
        resp = await test_client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.txt", io.BytesIO(txt), "text/plain")},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "ready"
    assert data["ingestion_progress"] == 100
    assert data["ingestion_attempts"] == 1


def test_trace_span_logs(caplog) -> None:  # type: ignore[no-untyped-def]
    from app.core.tracing import trace_span

    with caplog.at_level(logging.INFO, logger="app.tracing"), trace_span("test.span"):
        pass
    assert "trace span=test.span" in caplog.text
