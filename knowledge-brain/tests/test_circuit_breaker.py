from unittest.mock import AsyncMock, patch

import pytest

from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


def _breaker(**overrides) -> CircuitBreaker:
    defaults = {"name": "test", "failure_threshold": 3, "window_seconds": 60.0, "recovery_timeout": 60.0}
    return CircuitBreaker(**{**defaults, **overrides})


class _Clock:
    """A controllable stand-in for time.monotonic(), advanced explicitly per test."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


async def test_starts_closed_and_allows_a_successful_call_through():
    breaker = _breaker()
    func = AsyncMock(return_value="ok")

    result = await breaker.call(func)

    assert result == "ok"
    assert breaker._state == CircuitState.CLOSED
    func.assert_awaited_once()


async def test_stays_closed_below_the_failure_threshold():
    breaker = _breaker(failure_threshold=3)
    clock = _Clock()
    failing = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("app.core.circuit_breaker.time.monotonic", new=clock):
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(failing)

    assert breaker._state == CircuitState.CLOSED


async def test_opens_after_reaching_the_failure_threshold_within_the_window():
    breaker = _breaker(failure_threshold=3)
    clock = _Clock()
    failing = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("app.core.circuit_breaker.time.monotonic", new=clock):
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(failing)

    assert breaker._state == CircuitState.OPEN


async def test_rejects_calls_immediately_once_open_without_invoking_func():
    breaker = _breaker(failure_threshold=1)
    clock = _Clock()
    failing = AsyncMock(side_effect=RuntimeError("boom"))
    never_called = AsyncMock(return_value="should not run")

    with patch("app.core.circuit_breaker.time.monotonic", new=clock):
        with pytest.raises(RuntimeError):
            await breaker.call(failing)

        with pytest.raises(CircuitOpenError):
            await breaker.call(never_called)

    never_called.assert_not_awaited()


async def test_old_failures_outside_the_window_do_not_count_toward_the_threshold():
    """Two failures 61 seconds apart, with a 60s window, should never open the
    circuit — by the second failure, the first has already aged out.
    """
    breaker = _breaker(failure_threshold=2, window_seconds=60.0)
    clock = _Clock()
    failing = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("app.core.circuit_breaker.time.monotonic", new=clock):
        with pytest.raises(RuntimeError):
            await breaker.call(failing)

        clock.now = 61.0
        with pytest.raises(RuntimeError):
            await breaker.call(failing)

    assert breaker._state == CircuitState.CLOSED


async def test_a_success_fully_resets_the_failure_count():
    breaker = _breaker(failure_threshold=3)
    clock = _Clock()
    failing = AsyncMock(side_effect=RuntimeError("boom"))
    succeeding = AsyncMock(return_value="ok")

    with patch("app.core.circuit_breaker.time.monotonic", new=clock):
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(failing)

        await breaker.call(succeeding)

        # Two more failures right after a success shouldn't reach the
        # threshold of 3, since the success cleared the earlier two.
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(failing)

    assert breaker._state == CircuitState.CLOSED


async def test_stays_open_before_the_recovery_timeout_elapses():
    breaker = _breaker(failure_threshold=1, recovery_timeout=30.0)
    clock = _Clock()
    failing = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("app.core.circuit_breaker.time.monotonic", new=clock):
        with pytest.raises(RuntimeError):
            await breaker.call(failing)

        clock.now = 29.0
        with pytest.raises(CircuitOpenError):
            await breaker.call(failing)

    assert breaker._state == CircuitState.OPEN


async def test_moves_to_half_open_and_closes_on_a_successful_trial_call_after_recovery_timeout():
    breaker = _breaker(failure_threshold=1, recovery_timeout=30.0)
    clock = _Clock()
    failing = AsyncMock(side_effect=RuntimeError("boom"))
    succeeding = AsyncMock(return_value="recovered")

    with patch("app.core.circuit_breaker.time.monotonic", new=clock):
        with pytest.raises(RuntimeError):
            await breaker.call(failing)
        assert breaker._state == CircuitState.OPEN

        clock.now = 30.0
        result = await breaker.call(succeeding)

    assert result == "recovered"
    assert breaker._state == CircuitState.CLOSED


async def test_reopens_immediately_if_the_half_open_trial_call_fails():
    breaker = _breaker(failure_threshold=1, recovery_timeout=30.0)
    clock = _Clock()
    failing = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("app.core.circuit_breaker.time.monotonic", new=clock):
        with pytest.raises(RuntimeError):
            await breaker.call(failing)

        clock.now = 30.0
        with pytest.raises(RuntimeError):
            await breaker.call(failing)

    assert breaker._state == CircuitState.OPEN
