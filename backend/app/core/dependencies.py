from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.core.token_denylist import is_revoked
from app.models.user import User
from app.repositories.user_repository import UserRepository


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Authenticate via Bearer header OR httpOnly cookie (Phase E).

    Bearer is kept for API clients; the browser path uses the
    httpOnly cookie set by /auth/login, which JS cannot read.
    Either way the token is decoded, its jti checked against the
    logout denylist, and the user looked up with is_active enforced.
    A non-UUID sub, a revoked token, or an inactive user is 401.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token: str | None = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise credentials_exception
    try:
        payload = decode_access_token(token)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        if is_revoked(payload.get("jti")):
            raise credentials_exception
        user_uuid = UUID(user_id)
    except (JWTError, ValueError, AttributeError):
        raise credentials_exception

    repo = UserRepository(db)
    user = await repo.get_by_id(user_uuid)
    if user is None or not user.is_active:
        raise credentials_exception
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
