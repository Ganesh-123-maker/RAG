"""DB-backed access-token denylist (Phase 2).

Regression test for a live failure (2026-11-12): logout revoked the
token in memory only, so after a backend restart /me went 401 -> 200
for the logged-out token. Revocations are now persisted in the
revoked_access_tokens table and reloaded into memory at startup.

NOTE: the shared test_client fixture stubs get_current_user, which
is exactly the dependency that enforces the denylist, so these tests
build their own client that overrides only get_db.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.token_denylist as denylist
from app.core.database import get_db
from app.main import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def real_client(
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def _register_and_login(client: AsyncClient, email: str) -> str:
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": "Denylist User"},
    )
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def test_revocation_survives_simulated_restart(
    real_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(real_client, "denylist@example.com")

    logout = await real_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout.status_code == 200

    me = await real_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 401

    # Simulate a backend restart: the in-memory set is wiped, then
    # the lifespan reloads it from the DB. Without the fix there is
    # no row to reload and the token is accepted again (200).
    denylist.clear()
    counts = await denylist.load_into_memory(db_session)
    assert counts["loaded"] == 1

    me_after_restart = await real_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_after_restart.status_code == 401


async def test_expired_revocations_pruned_on_load(
    db_session: AsyncSession,
) -> None:
    # An already-expired revocation must not linger in memory or DB.
    expired_jti = "expired-jti-0000"
    await denylist.revoke_persisted(
        db_session, expired_jti, datetime.now(UTC) - timedelta(minutes=1)
    )
    assert denylist.is_revoked(expired_jti)

    denylist.clear()
    counts = await denylist.load_into_memory(db_session)
    assert counts["loaded"] == 0
    assert counts["pruned_expired"] == 1
    assert not denylist.is_revoked(expired_jti)


async def test_double_revoke_same_jti_does_not_violate_pk(
    db_session: AsyncSession,
) -> None:
    # revoke_persisted merges instead of inserting blindly, so a
    # second revoke of the same jti cannot violate the primary key.
    jti = "double-revoke-jti"
    exp = datetime.now(UTC) + timedelta(minutes=60)
    await denylist.revoke_persisted(db_session, jti, exp)
    await denylist.revoke_persisted(db_session, jti, exp)
    assert denylist.is_revoked(jti)
