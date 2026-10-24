from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger("app.tracing")


@contextmanager
def trace_span(name: str, **fields: object) -> Iterator[None]:
    """Log-based tracing span (Phase E).

    Emits one JSON-ish log line per span with name, duration_ms and
    any fields. This is NOT LangSmith/Langfuse: no tracing key is
    required to boot, and no spans leave the process. It is the
    extension point for a real tracer — a LangSmith/Langfuse
    integration would wrap the same span boundaries (graph nodes)
    and emit to its SDK instead of, or as well as, this log line.
    """
    start = time.monotonic()
    try:
        yield
    finally:
        duration_ms = (time.monotonic() - start) * 1000
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        logger.info(
            "trace span=%s duration_ms=%.1f %s",
            name,
            duration_ms,
            extra,
        )
