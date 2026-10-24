from __future__ import annotations

import time
from enum import Enum


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open: fail fast, do not call."""


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Small synchronous circuit breaker for a downstream dependency.

    Closed: calls pass through; ``failure_threshold`` consecutive
    failures open the circuit. Open: calls raise CircuitOpenError
    immediately until ``cooldown_seconds`` pass. Half-open: one trial
    call is allowed; success closes, failure re-opens. State is
    in-memory and per-process (single-instance limit, as with the
    rate limiter). Callers must map CircuitOpenError to their own
    safe error type (e.g. AgentError / 502) — this module never
    leaks provider internals.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self.state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False

    def _maybe_half_open(self, now: float) -> None:
        if (
            self.state == CircuitState.OPEN
            and self._opened_at is not None
            and now - self._opened_at >= self.cooldown_seconds
        ):
            self.state = CircuitState.HALF_OPEN
            self._trial_in_flight = False

    def before_call(self) -> None:
        now = time.monotonic()
        self._maybe_half_open(now)
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError("Downstream service temporarily unavailable.")
        if self.state == CircuitState.HALF_OPEN:
            if self._trial_in_flight:
                raise CircuitOpenError("Downstream service temporarily unavailable.")
            self._trial_in_flight = True

    def on_success(self) -> None:
        self.state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None
        self._trial_in_flight = False

    def on_failure(self) -> None:
        self._consecutive_failures += 1
        self._trial_in_flight = False
        if self._consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self._opened_at = time.monotonic()

    def reset(self) -> None:
        self.on_success()
