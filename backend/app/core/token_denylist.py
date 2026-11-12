from __future__ import annotations

import threading
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.revoked_access_token import RevokedAccessToken

# In-memory revoked-token set (Phase E), now backed by the
# revoked_access_tokens table (Phase 2). The set alone was cleared
# on every backend restart, so a token revoked by logout was
# accepted again after a restart (proven live 2026-11-12: /me went
# 401 -> 200 across a restart). The DB rows survive restarts: the
# lifespan loads unexpired rows into this set at boot (and prunes
# expired rows), and logout writes both the set and a row. The set
# stays the hot path for the per-request is_revoked check, so the
# auth dependency never does a DB round-trip per request.
_lock = threading.Lock()
_revoked: set[str] = set()


def revoke(jti: str) -> None:
    with _lock:
        _revoked.add(jti)


def is_revoked(jti: str | None) -> bool:
    if not jti:
        return False
    with _lock:
        return jti in _revoked


def clear() -> None:
    with _lock:
        _revoked.clear()


async def load_into_memory(db: AsyncSession) -> dict[str, int]:
    """Load unexpired revoked JTIs from the DB into the set; prune expired rows.

    Called at startup (best-effort: a failure only logs a warning in
    the lifespan, never breaks boot). Returns counts for logging.
    """
    now = datetime.now(UTC)
    expired = await db.execute(
        delete(RevokedAccessToken).where(RevokedAccessToken.expires_at <= now)
    )
    rows = (
        await db.execute(
            select(RevokedAccessToken.jti).where(RevokedAccessToken.expires_at > now)
        )
    ).scalars().all()
    await db.commit()
    with _lock:
        _revoked.update(rows)
    return {"loaded": len(rows), "pruned_expired": expired.rowcount or 0}


async def revoke_persisted(db: AsyncSession, jti: str, expires_at: datetime) -> None:
    """Revoke in memory AND persist a row, so logout survives restarts."""
    revoke(jti)
    # merge(): a second logout of the same token updates the row
    # instead of violating the jti primary key.
    await db.merge(RevokedAccessToken(jti=jti, expires_at=expires_at))
    await db.commit()
