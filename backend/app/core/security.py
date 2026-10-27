from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Response
from jose import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    subject: str | Any, expires_delta: timedelta | None = None
) -> str:
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    # jti enables logout revocation via the token denylist (Phase E).
    payload = {"sub": str(subject), "exp": expire, "jti": str(uuid.uuid4())}
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def set_auth_cookie(response: Response, token: str) -> None:
    """Set the browser auth cookie (Phase E).

    httpOnly always (JS can never read it — that is the point);
    Secure only in production, because Secure cookies are not sent
    over plain localhost http and would break local development;
    SameSite=Lax (CSRF-resistant for top-level navigation, and the
    app is same-origin via the Next.js rewrite proxy anyway).
    max_age matches the JWT lifetime exactly, fixing the old
    1-day cookie vs 60-minute token drift.
    """
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=(settings.ENVIRONMENT or "development").lower() == "production",
        samesite="lax",
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key="access_token", path="/")


def set_refresh_cookie(response: Response, token: str) -> None:
    """Set the refresh-token cookie: same protections as the access
    cookie (httpOnly always, Secure only in production), but scoped
    to the auth routes (path=/api/v1/auth) so it is only sent where
    the refresh endpoint can use it, and with the refresh lifetime.
    """
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=(settings.ENVIRONMENT or "development").lower() == "production",
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key="refresh_token", path="/api/v1/auth")


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
