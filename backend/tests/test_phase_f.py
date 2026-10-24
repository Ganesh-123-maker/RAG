"""Phase F: conversation rename (owner-scoped PATCH endpoint)."""
from __future__ import annotations

import uuid

import pytest

from app.models.conversation import Conversation
from app.repositories.conversation_repository import ConversationRepository


async def _make_conversation(db_session, owner_id):
    conv = Conversation(owner_id=owner_id, title="Old title")
    db_session.add(conv)
    await db_session.flush()
    return conv


async def test_rename_success(test_client, db_session, fake_user):
    conv = await _make_conversation(db_session, fake_user.id)
    resp = await test_client.patch(
        f"/api/v1/chat/conversations/{conv.id}", json={"title": "  New title  "}
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "New title"


async def test_rename_empty_title_rejected(test_client, db_session, fake_user):
    conv = await _make_conversation(db_session, fake_user.id)
    resp = await test_client.patch(
        f"/api/v1/chat/conversations/{conv.id}", json={"title": "   "}
    )
    assert resp.status_code == 422


async def test_rename_other_users_conversation_is_404(test_client, db_session, fake_user):
    conv = await _make_conversation(db_session, uuid.uuid4())
    resp = await test_client.patch(
        f"/api/v1/chat/conversations/{conv.id}", json={"title": "Hijack"}
    )
    assert resp.status_code == 404


async def test_rename_missing_conversation_is_404(test_client, fake_user):
    resp = await test_client.patch(
        f"/api/v1/chat/conversations/{uuid.uuid4()}", json={"title": "Nope"}
    )
    assert resp.status_code == 404


async def test_repository_update_title_is_owner_scoped(db_session, fake_user):
    repo = ConversationRepository(db_session)
    conv = await _make_conversation(db_session, uuid.uuid4())
    assert await repo.update_title_for_owner(conv.id, fake_user.id, "X") is None
