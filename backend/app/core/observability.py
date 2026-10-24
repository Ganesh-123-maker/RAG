from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import time
import uuid
from collections import defaultdict

logger = logging.getLogger("app.requests")

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def normalize_path(path: str) -> str:
    """Collapse UUID segments so metrics cardinality stays bounded."""
    return _UUID_RE.sub("{id}", path)


class Metrics:
    """Minimal in-process metrics store.

    Deliberately NOT prometheus_client: this endpoint renders
    Prometheus text format from plain counters, so /metrics works
    with no new dependency. It is labelled a minimal metrics
    endpoint in docs, never claimed to be a Prometheus client
    integration. Counts are per-process and lost on restart.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, str, int], int] = defaultdict(int)
        self._hist: dict[tuple[str, str], list[float]] = defaultdict(list)

    def observe(self, method: str, path: str, status: int, duration: float) -> None:
        with self._lock:
            self._counts[(method, normalize_path(path), status)] += 1
            self._hist[(method, normalize_path(path))].append(duration)

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._hist.clear()

    def render(self) -> str:
        lines = [
            "# HELP rag_http_requests_total Total HTTP requests.",
            "# TYPE rag_http_requests_total counter",
        ]
        with self._lock:
            for (method, path, status), count in sorted(self._counts.items()):
                lines.append(
                    f'rag_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
                )
            lines.append("# HELP rag_http_request_duration_seconds Request latency.")
            lines.append("# TYPE rag_http_request_duration_seconds histogram")
            for (method, path), values in sorted(self._hist.items()):
                for bucket in _BUCKETS:
                    n = sum(1 for v in values if v <= bucket)
                    lines.append(
                        f'rag_http_request_duration_seconds_bucket{{method="{method}",path="{path}",le="{bucket}"}} {n}'
                    )
                lines.append(
                    f'rag_http_request_duration_seconds_bucket{{method="{method}",path="{path}",le="+Inf"}} {len(values)}'
                )
                lines.append(
                    f'rag_http_request_duration_seconds_sum{{method="{method}",path="{path}"}} {sum(values):.6f}'
                )
                lines.append(
                    f'rag_http_request_duration_seconds_count{{method="{method}",path="{path}"}} {len(values)}'
                )
        return "\n".join(lines) + "\n"


metrics = Metrics()


class RequestIDMetricsMiddleware:
    """Pure ASGI middleware: request IDs, JSON request logs, metrics.

    Generates (or propagates, if the client sent one) an
    X-Request-ID, echoes it on the response, and logs one JSON line
    per request with method, path, status and duration. It does not
    buffer bodies, so SSE streaming passes through unchanged.
    """

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        request_id = headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        start = time.monotonic()
        status_code = 500

        async def send_with_id(message) -> None:  # type: ignore[no-untyped-def]
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-request-id", request_id.encode()),
                    ],
                }
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            duration = time.monotonic() - start
            method = scope.get("method", "")
            path = scope.get("path", "")
            metrics.observe(method, path, status_code, duration)
            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "method": method,
                        "path": normalize_path(path),
                        "status": status_code,
                        "duration_ms": round(duration * 1000, 1),
                    }
                )
            )
            request_id_var.reset(token)


def get_request_id() -> str:
    return request_id_var.get("")
