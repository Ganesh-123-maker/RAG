from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.refresh_token import RefreshToken
from app.models.user import User

# One generic 401 for every refresh failure (unknown, expired,
# revoked, reused): the response must not leak which reason applied,
# or an attacker could probe token validity.
_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired refresh token",
)


def hash_refresh_token(raw: str) -> str:
    """SHA-256 hex of the opaque token. Only this is ever stored."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_naive_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for DateTime(timezone=True);
    # Postgres returns aware ones. Normalise before comparing.
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


class RefreshTokenService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def issue(self, user: User) -> str:
        """Create a new token in a new family; return the raw token.

        Only the hash is persisted. The caller commits: login already
        commits its own changes, and rotate commits after revoking
        the presented token, so issue itself only flushes.
        """
        settings = get_settings()
        raw = secrets.token_urlsafe(32)
        row = RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw),
            family_id=uuid.uuid4(),
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        self._db.add(row)
        await self._db.flush()
        return raw

    async def rotate(self, raw: str) -> tuple[str, uuid.UUID]:
        """Rotate a presented token; return (new raw token, user id).

        Success revokes the presented token (revoked_at +
        replaced_by_id) and issues a new token in the same family.
        Presenting an already-replaced token is reuse (a stolen
        token replayed after the owner rotated): the whole family is
        revoked and the request is 401. Expired, logout-revoked, or
        unknown tokens are 401 without family revocation and without
        leaking which reason applied.
        """
        settings = get_settings()
        row = await self._lookup(raw)
        if row is None:
            raise _INVALID
        if row.replaced_by_id is not None:
            # Reuse detected: kill the whole family, including the
            # token the legitimate owner is currently holding.
            await self._revoke_family(row.family_id)
            await self._db.commit()
            raise _INVALID
        if row.revoked_at is not None:
            raise _INVALID
        if _as_naive_utc(row.expires_at) <= datetime.now(UTC).replace(tzinfo=None):
            raise _INVALID
        user = await self._db.get(User, row.user_id)
        if user is None or not user.is_active:
            raise _INVALID
        new_raw = secrets.token_urlsafe(32)
        new_row = RefreshToken(
            user_id=row.user_id,
            token_hash=hash_refresh_token(new_raw),
            family_id=row.family_id,
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        self._db.add(new_row)
        await self._db.flush()
        row.revoked_at = datetime.now(UTC)
        row.replaced_by_id = new_row.id
        await self._db.commit()
        return new_raw, row.user_id

    async def revoke_presented(self, raw: str) -> None:
        """Revoke the presented token (logout). Unknown tokens are a
        no-op: logout must succeed even if the token is already gone.
        """
        row = await self._lookup(raw)
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await self._db.commit()

    async def _lookup(self, raw: str) -> RefreshToken | None:
        result = await self._db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(raw)
            )
        )
        return result.scalars().first()

    async def _revoke_family(self, family_id: uuid.UUID) -> None:
        result = await self._db.execute(
            select(RefreshToken).where(RefreshToken.family_id == family_id)
        )
        now = datetime.now(UTC)
        for row in result.scalars().all():
            if row.revoked_at is None:
                row.revoked_at = now
