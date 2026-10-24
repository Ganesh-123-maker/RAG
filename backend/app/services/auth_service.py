from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import RegisterRequest, TokenResponse


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = UserRepository(db)

    async def register(self, payload: RegisterRequest) -> User:
        if await self._repo.exists_by_email(payload.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        user = await self._repo.create(
            email=payload.email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
        )
        return user

    async def login(self, email: str, password: str) -> TokenResponse:
        settings = get_settings()
        user = await self._repo.get_by_email(email)
        if user is not None and user.locked_until is not None:
            locked_until = user.locked_until
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=UTC)
            if locked_until > datetime.now(UTC):
                # 429 (not 401) so clients can distinguish lockout from
                # a wrong password, with Retry-After in seconds.
                retry_after = int((locked_until - datetime.now(UTC)).total_seconds())
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Account temporarily locked after repeated failed logins.",
                    headers={"Retry-After": str(max(1, retry_after))},
                )
        if user is None or not verify_password(password, user.hashed_password):
            if user is not None:
                await self._repo.record_failed_login(user)
                if (
                    user.failed_login_attempts or 0
                ) >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                    user.locked_until = datetime.now(UTC) + timedelta(
                        minutes=settings.LOCKOUT_MINUTES
                    )
                # Explicit commit: get_db rolls back on HTTPException,
                # which would silently discard the lockout counter.
                await self._db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        await self._repo.reset_failed_logins(user)
        await self._db.commit()
        token = create_access_token(subject=user.id)
        return TokenResponse(access_token=token, token_type="bearer")
