"""Tests for refresh-token rotation, reuse detection, and logout."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.refresh_token import RefreshToken


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _setup(db_session: AsyncSession) -> None:
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)


def _teardown() -> None:
    app.dependency_overrides.clear()


async def _register_and_login(client: AsyncClient, email: str) -> tuple[str, str]:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "securepass123"},
    )
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "securepass123"},
    )
    assert response.status_code == 200
    raw_refresh = response.cookies.get("refresh_token")
    assert raw_refresh
    return response.json()["access_token"], raw_refresh


async def _refresh_with_cookie(raw: str) -> int:
    async with _client() as client:
        response = await client.post(
            "/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={raw}"}
        )
    return response.status_code


@pytest.mark.asyncio
async def test_login_issues_refresh_cookie_and_stores_only_hash(
    db_session: AsyncSession,
) -> None:
    _setup(db_session)
    try:
        async with _client() as client:
            _, raw_refresh = await _register_and_login(
                client, "refresh-login@example.com"
            )
            # Only the hash is persisted, never the raw token.
            rows = (await db_session.execute(select(RefreshToken))).scalars().all()
            assert len(rows) == 1
            assert (
                rows[0].token_hash == hashlib.sha256(raw_refresh.encode()).hexdigest()
            )
            assert rows[0].token_hash != raw_refresh
            assert rows[0].revoked_at is None
            assert rows[0].replaced_by_id is None
    finally:
        _teardown()


@pytest.mark.asyncio
async def test_login_sets_refresh_cookie_attributes(
    db_session: AsyncSession,
) -> None:
    _setup(db_session)
    try:
        async with _client() as client:
            await client.post(
                "/api/v1/auth/register",
                json={"email": "cookie-attrs@example.com", "password": "securepass123"},
            )
            response = await client.post(
                "/api/v1/auth/login",
                data={
                    "username": "cookie-attrs@example.com",
                    "password": "securepass123",
                },
            )
        set_cookie = response.headers.get("set-cookie", "")
        assert "refresh_token=" in set_cookie
        assert "httponly" in set_cookie.lower()
        assert "path=/api/v1/auth" in set_cookie.lower()
    finally:
        _teardown()


@pytest.mark.asyncio
async def test_refresh_rotates_and_old_token_rejected(
    db_session: AsyncSession,
) -> None:
    _setup(db_session)
    try:
        async with _client() as client:
            _, raw_refresh = await _register_and_login(
                client, "refresh-rotate@example.com"
            )
            response = await client.post("/api/v1/auth/refresh")
        assert response.status_code == 200
        assert "access_token" in response.json()
        new_raw = response.cookies.get("refresh_token")
        assert new_raw and new_raw != raw_refresh
        # The new token still works (checked before any reuse
        # presentation: presenting the old token would be reuse
        # detection and would revoke this one too -- that is the
        # next test's job).
        assert await _refresh_with_cookie(new_raw) == 200
    finally:
        _teardown()


@pytest.mark.asyncio
async def test_reuse_of_rotated_token_revokes_whole_family(
    db_session: AsyncSession,
) -> None:
    _setup(db_session)
    try:
        async with _client() as client:
            _, raw_refresh = await _register_and_login(
                client, "refresh-reuse@example.com"
            )
            response = await client.post("/api/v1/auth/refresh")
        assert response.status_code == 200
        new_raw = response.cookies.get("refresh_token")
        assert new_raw
        # Attacker replays the old (rotated) token: reuse detected.
        assert await _refresh_with_cookie(raw_refresh) == 401
        # The whole family is revoked, so the owner's current token
        # is dead too -- that is the point of reuse detection.
        assert await _refresh_with_cookie(new_raw) == 401
    finally:
        _teardown()


@pytest.mark.asyncio
async def test_expired_refresh_token_rejected(
    db_session: AsyncSession,
) -> None:
    _setup(db_session)
    try:
        async with _client() as client:
            _, raw_refresh = await _register_and_login(
                client, "refresh-expired@example.com"
            )
        rows = (await db_session.execute(select(RefreshToken))).scalars().all()
        assert len(rows) == 1
        rows[0].expires_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.commit()
        assert await _refresh_with_cookie(raw_refresh) == 401
    finally:
        _teardown()


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(
    db_session: AsyncSession,
) -> None:
    _setup(db_session)
    try:
        async with _client() as client:
            access_token, raw_refresh = await _register_and_login(
                client, "refresh-logout@example.com"
            )
            response = await client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        assert response.status_code == 200
        # Even presenting the raw token directly (bypassing the
        # cleared cookie jar) must now fail: it was revoked in the DB.
        assert await _refresh_with_cookie(raw_refresh) == 401
    finally:
        _teardown()


@pytest.mark.asyncio
async def test_refresh_with_no_cookie_is_401(
    db_session: AsyncSession,
) -> None:
    _setup(db_session)
    try:
        async with _client() as client:
            response = await client.post("/api/v1/auth/refresh")
        assert response.status_code == 401
    finally:
        _teardown()


@pytest.mark.asyncio
async def test_refresh_unknown_token_is_401_without_leak(
    db_session: AsyncSession,
) -> None:
    _setup(db_session)
    try:
        assert await _refresh_with_cookie("not-a-real-token") == 401
    finally:
        _teardown()
