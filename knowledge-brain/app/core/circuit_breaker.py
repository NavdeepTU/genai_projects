import logging
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """The three states a circuit breaker can be in."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""


class CircuitBreaker:
    """Stops calling a failing external service until it's likely recovered.

    Tracks failures in a rolling time window. After `failure_threshold`
    failures within `window_seconds`, the circuit opens and rejects calls
    immediately for `recovery_timeout` seconds, instead of letting every
    request separately wait for a doomed call to time out.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        window_seconds: float = 60.0,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.recovery_timeout = recovery_timeout

        self._state = CircuitState.CLOSED
        self._failure_timestamps: list[float] = []
        self._opened_at: float | None = None

    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        """Run func() through the circuit breaker."""
        self._maybe_recover()

        if self._state == CircuitState.OPEN:
            logger.warning("Circuit '%s' is open — rejecting call without trying", self.name)
            raise CircuitOpenError(f"Circuit '{self.name}' is open")

        try:
            result = await func()
        except Exception:
            self._record_failure()
            raise
        else:
            self._record_success()
            return result

    def _maybe_recover(self) -> None:
        """Move from OPEN to HALF_OPEN once the cooldown has passed."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info("Circuit '%s' entering half-open — allowing a trial call", self.name)

    def _record_failure(self) -> None:
        now = time.monotonic()
        self._failure_timestamps.append(now)
        self._failure_timestamps = [
            t for t in self._failure_timestamps if now - t <= self.window_seconds
        ]

        if self._state == CircuitState.HALF_OPEN or len(self._failure_timestamps) >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = now
            logger.error(
                "Circuit '%s' opened after %d failures in %.0fs",
                self.name,
                len(self._failure_timestamps),
                self.window_seconds,
            )

    def _record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit '%s' recovered — closing", self.name)
        self._state = CircuitState.CLOSED
        self._failure_timestamps.clear()
        self._opened_at = None
