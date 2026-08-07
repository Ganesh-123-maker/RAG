"""Tests for auth API routes."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.database import get_db
from app.main import app


@pytest.mark.asyncio
async def test_register_success(db_session: AsyncSession) -> None:
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)

    from httpx import ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": "securepass123", "full_name": "Alice"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "user@example.com"
    assert "id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(db_session: AsyncSession) -> None:
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)

    from httpx import ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/register",
            json={"email": "dup@example.com", "password": "securepass123"},
        )
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "dup@example.com", "password": "securepass123"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_register_weak_password(db_session: AsyncSession) -> None:
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)

    from httpx import ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "weak@example.com", "password": "short"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success(db_session: AsyncSession) -> None:
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)

    from httpx import ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/register",
            json={"email": "login@example.com", "password": "goodpassword"},
        )
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "login@example.com", "password": "goodpassword"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_login_wrong_password(db_session: AsyncSession) -> None:
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides.pop(get_current_user, None)

    from httpx import ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/register",
            json={"email": "bad@example.com", "password": "goodpassword"},
        )
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "bad@example.com", "password": "wrongpassword"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 401
