from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RevokedAccessToken(Base):
    """DB-backed access-token denylist (Phase 2).

    The in-memory set in app/core/token_denylist.py is cleared on
    every backend restart, so a token revoked by logout was accepted
    again after a restart (proven live 2026-11-12: /me went 401 ->
    200 across a restart). Rows here survive restarts; the lifespan
    loads unexpired rows into the in-memory set at boot, and logout
    writes both. Rows are pruned when loaded (expired rows are
    deleted) and keyed by jti so a token is revoked at most once.
    """

    __tablename__ = "revoked_access_tokens"

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<RevokedAccessToken jti={self.jti}>"
