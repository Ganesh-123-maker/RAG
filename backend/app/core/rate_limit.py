from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, status

from app.core.config import get_settings


class RateLimitExceeded(HTTPException):
    """429 with a Retry-After header, for limiter rejections."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": str(max(1, retry_after))},
        )
        self.retry_after = max(1, retry_after)


class InMemoryRateLimiter:
    """Fixed-window, in-memory rate limiter.

    Single-instance only: counts live in this process and are lost on
    restart, and a multi-replica deployment would enforce the limit
    per replica, not globally. That is an accepted Phase E limit,
    documented in docs/phase-e-report.md; Redis is the Phase F+
    upgrade if horizontal scaling is ever needed.
    """

    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = defaultdict(int)
        self._enabled_override: bool | None = None

    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return self._enabled_override
        settings = get_settings()
        if settings.RATE_LIMIT_ENABLED is not None:
            return settings.RATE_LIMIT_ENABLED
        # Default off in tests: the suite makes many calls as one user
        # in one process, and a global limiter would make tests order
        # dependent. Rate-limit tests enable it explicitly.
        return (settings.ENVIRONMENT or "development").lower() != "test"

    def set_enabled_for_tests(self, value: bool) -> None:
        self._enabled_override = value

    def clear(self) -> None:
        self._counts.clear()

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        """Raise RateLimitExceeded if ``key`` has exceeded ``limit``."""
        if not self.enabled or limit <= 0:
            return
        now = int(time.time())
        window = now // max(1, window_seconds)
        bucket = (key, window)
        self._counts[bucket] += 1
        if self._counts[bucket] > limit:
            raise RateLimitExceeded(retry_after=window_seconds)


# Process-global limiter; routers share it so auth/upload/chat limits
# are enforced consistently within one instance.
limiter = InMemoryRateLimiter()


def check_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    limiter.check(key, limit, window_seconds)
