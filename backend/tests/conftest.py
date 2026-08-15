from __future__ import annotations

import uuid
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.core.database as db_module
from app.core.database import Base, get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.user import User

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    old_session_local = db_module.AsyncSessionLocal
    old_engine = db_module.engine
    db_module.AsyncSessionLocal = session_factory
    db_module.engine = engine

    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

    db_module.AsyncSessionLocal = old_session_local
    db_module.engine = old_engine


@pytest_asyncio.fixture(scope="function")
async def fake_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password="$2b$12$fakehashfakehashfakehash",
        full_name="Test User",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture(scope="function")
async def test_client(db_session: AsyncSession, fake_user: User) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
