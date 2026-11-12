"""Streamed-chat persist must not deadlock on its own request session.

Regression test for a live browser failure (2026-11-12): the answer
was generated and cited correctly, then its INSERT failed with
"database is locked" and the UI showed nothing.

Root cause: POST /chat/stream added the user message with flush()
only, so the request session held the SQLite write uncommitted for
the whole stream (get_db commits only after the response ends),
while persist() in the generator's finally block opened a SECOND
session to insert the assistant message. One writer blocks the
other; the persist waited out the busy timeout and failed.

The suite's :memory:/StaticPool fixtures share a single connection,
so they can never show this. This test uses a real file database
with separate sessions per request, like production.
"""

from __future__ import annotations

import importlib
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.config as config_module
import app.core.database as db_module
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def test_stream_persists_answer_on_file_db(tmp_path, monkeypatch):
    db_file = tmp_path / "stream.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    original_base = db_module.Base
    config_module.get_settings.cache_clear()
    importlib.reload(db_module)
    try:
        async with db_module.engine.begin() as conn:
            await conn.run_sync(original_base.metadata.create_all)

        user = User(
            id=uuid.uuid4(),
            email="stream-file@example.com",
            hashed_password="x",
            full_name="Stream User",
            is_active=True,
        )
        async with db_module.AsyncSessionLocal() as session:
            session.add(user)
            await session.commit()

        async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
            async with db_module.AsyncSessionLocal() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: user

        async def fake_stream(self, **kwargs):
            yield {"type": "status", "status": "started"}
            yield {"type": "token", "token": "Hello "}
            yield {"type": "token", "token": "world!"}
            yield {"type": "citations", "citations": []}
            yield {"type": "done", "answer": "Hello world!", "citations": []}

        with patch("app.routers.chat.AgentService.run_stream", fake_stream):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/chat/stream", json={"question": "Stream this answer"}
                )
                assert resp.status_code == 200
                assert "Hello world!" in resp.text

                convs = await client.get("/api/v1/chat/conversations")
                conv_id = convs.json()["conversations"][0]["id"]
                detail = await client.get(f"/api/v1/chat/conversations/{conv_id}")
                messages = detail.json()["messages"]
                assistant = [m for m in messages if m["role"] == "assistant"]
                # Without the fix this is empty: the persist INSERT
                # waited out the busy timeout against the request
                # session's own uncommitted user-message write.
                assert len(assistant) == 1
                assert assistant[0]["content"] == "Hello world!"
    finally:
        app.dependency_overrides.clear()
        await db_module.engine.dispose()
        config_module.get_settings.cache_clear()
        importlib.reload(db_module)
