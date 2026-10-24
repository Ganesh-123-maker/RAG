from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        # Parse inside the try: a syntactically valid JWT with a non-UUID
        # sub previously raised an uncaught ValueError (HTTP 500). It is
        # an authentication failure, so it must be 401.
        user_uuid = UUID(user_id)
    except (JWTError, ValueError, AttributeError):
        raise credentials_exception

    repo = UserRepository(db)
    user = await repo.get_by_id(user_uuid)
    if user is None or not user.is_active:
        # Inactive users authenticate no further; 401 (not 403) so the
        # client treats it exactly like any other invalid credential.
        raise credentials_exception
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
