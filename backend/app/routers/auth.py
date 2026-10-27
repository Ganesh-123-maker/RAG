from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import CurrentUser
from app.core.rate_limit import check_rate_limit
from app.core.security import (
    clear_auth_cookie,
    clear_refresh_cookie,
    create_access_token,
    decode_access_token,
    set_auth_cookie,
    set_refresh_cookie,
)
from app.core.token_denylist import revoke
from app.repositories.user_repository import UserRepository
from app.schemas.auth import RegisterRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthService
from app.services.refresh_token_service import RefreshTokenService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    payload: RegisterRequest, db: AsyncSession = Depends(get_db)
) -> UserResponse:
    # Rate-limited per email (no Request param, so direct router
    # calls in tests keep their existing signature). Login is
    # rate-limited per IP separately, where Request is already a
    # parameter.
    settings = get_settings()
    check_rate_limit(
        f"register:{payload.email}", settings.AUTH_RATE_LIMIT_PER_MINUTE, 60
    )
    svc = AuthService(db)
    user = await svc.register(payload)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    check_rate_limit(
        f"login:{request.client.host if request.client else 'unknown'}",
        settings.AUTH_RATE_LIMIT_PER_MINUTE,
        60,
    )
    email = None
    password = None

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            email = body.get("email") or body.get("username")
            password = body.get("password")
        except Exception:  # noqa: BLE001, S110 -- malformed body already handled by the 422 below
            pass
    else:
        try:
            form = await request.form()
            email = form.get("username") or form.get("email")
            password = form.get("password")
        except Exception:  # noqa: BLE001, S110 -- malformed form already handled by the 422 below
            pass

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Email/username and password are required",
        )

    svc = AuthService(db)
    result = await svc.login(email=str(email), password=str(password))
    # Browser path: httpOnly cookie (JS never sees the token). The
    # token is still returned in the body for API clients.
    set_auth_cookie(response, result.access_token)
    # Refresh token: same browser-only handling, scoped cookie.
    user = await UserRepository(db).get_by_email(str(email))
    if user is not None:
        refresh_svc = RefreshTokenService(db)
        raw_refresh = await refresh_svc.issue(user)
        await db.commit()
        set_refresh_cookie(response, raw_refresh)
    return result


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Rotate the refresh cookie into a fresh access token.

    Reads only the httpOnly `refresh_token` cookie (JS never holds
    the token). Rotation revokes the presented token and issues a
    new one in the same family; reuse of a rotated token revokes
    the whole family (see RefreshTokenService). Every failure is
    the same generic 401.
    """
    raw = request.cookies.get("refresh_token")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    refresh_svc = RefreshTokenService(db)
    new_raw, user_id = await refresh_svc.rotate(raw)
    access_token = create_access_token(subject=user_id)
    set_auth_cookie(response, access_token)
    set_refresh_cookie(response, new_raw)
    return TokenResponse(access_token=access_token, token_type="bearer")


@router.post("/logout")
async def logout(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Revoke the current token (denylist), revoke the presented
    refresh token, and clear both cookies. Logout must succeed even
    if either token is already invalid.
    """
    token: str | None = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.cookies.get("access_token")
    if token:
        try:
            payload = decode_access_token(token)
            if payload.get("jti"):
                revoke(payload["jti"])
        except Exception:  # noqa: BLE001, S110 -- logout must succeed even if the token is already invalid
            pass
    raw_refresh = request.cookies.get("refresh_token")
    if raw_refresh:
        await RefreshTokenService(db).revoke_presented(raw_refresh)
    response = JSONResponse(content={"detail": "Logged out"})
    clear_auth_cookie(response)
    clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
    )
