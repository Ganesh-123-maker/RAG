from __future__ import annotations

import uuid
from datetime import date

from fastapi import HTTPException, status

from app.core.config import get_settings

# In-memory daily quotas (single-instance, lost on restart — same
# documented limit as the rate limiter). Counts are per UTC date.
_counts: dict[tuple[str, str], int] = {}
_tokens: dict[tuple[str, str], int] = {}


def _today() -> str:
    return date.today().isoformat()


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 4), NOT metered OpenAI usage.

    The agent service does not return usage, so this is a cost guard
    only. Never report it as actual billed tokens.
    """
    return max(1, len(text) // 4)


def check_daily_quota(user_id: uuid.UUID, settings=None) -> None:
    # settings is injectable so tests can exercise the quota logic
    # without changing the process environment (production code
    # always passes None and uses the real settings).
    if settings is None:
        settings = get_settings()
    if (settings.ENVIRONMENT or "development").lower() == "test":
        return
    key = (str(user_id), _today())
    if _counts.get(key, 0) >= settings.DAILY_CHAT_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily chat request quota exceeded.",
            headers={"Retry-After": "86400"},
        )
    if _tokens.get(key, 0) >= settings.DAILY_TOKEN_BUDGET_EST:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily estimated token budget exceeded.",
            headers={"Retry-After": "86400"},
        )


def record_daily_usage(user_id: uuid.UUID, est_tokens: int) -> None:
    key = (str(user_id), _today())
    _counts[key] = _counts.get(key, 0) + 1
    _tokens[key] = _tokens.get(key, 0) + max(0, est_tokens)


def clear() -> None:
    _counts.clear()
    _tokens.clear()
