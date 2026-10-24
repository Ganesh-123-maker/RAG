from __future__ import annotations

import threading

# In-memory revoked-token set (Phase E). Single-instance and cleared
# on restart: a revoked token is accepted again only if the process
# restarts before the token expires (access tokens live 60 minutes,
# so the window is bounded). A persistent denylist (DB/Redis) is the
# upgrade if multi-instance deployment is ever needed. A refresh
# flow was deliberately NOT added in this phase: rotation + reuse
# detection is easy to get wrong, and a half-built refresh flow is
# worse than a documented deferral (see docs/phase-e-report.md).
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
