"""Tests for hello_agent.tools.circuit_breaker.CircuitBreaker."""
from __future__ import annotations

import time

import pytest

from hello_agent.tools.circuit_breaker import (
    CircuitBreaker,
    check_breaker,
    record_failure,
    record_success,
)


def _fresh_breaker(fail_threshold: int = 2, cooldown_seconds: float = 0.05) -> CircuitBreaker:
    """A breaker with a tight cooldown so tests stay fast."""
    return CircuitBreaker(
        fail_threshold=fail_threshold,
        window_seconds=10.0,
        cooldown_seconds=cooldown_seconds,
    )


def test_initial_state_is_closed() -> None:
    """A fresh tool slot starts in the closed state and allows calls."""
    cb = _fresh_breaker()
    assert cb.state("t") == CircuitBreaker.STATE_CLOSED
    assert cb.allow("t") is True


def test_failures_below_threshold_keep_state_closed() -> None:
    """Fewer than `fail_threshold` failures must NOT open the circuit."""
    cb = _fresh_breaker(fail_threshold=3)
    cb.record_failure("t")
    cb.record_failure("t")
    assert cb.state("t") == CircuitBreaker.STATE_CLOSED
    assert cb.allow("t") is True


def test_failures_at_threshold_open_circuit() -> None:
    """`fail_threshold` consecutive failures open the circuit; allow()=False."""
    cb = _fresh_breaker(fail_threshold=2)
    cb.record_failure("t")
    cb.record_failure("t")
    assert cb.state("t") == CircuitBreaker.STATE_OPEN
    assert cb.allow("t") is False


def test_open_circuit_transitions_to_half_open_after_cooldown() -> None:
    """After `cooldown_seconds` elapses, the next allow() moves to half_open."""
    cb = _fresh_breaker(fail_threshold=1, cooldown_seconds=0.05)
    cb.record_failure("t")
    assert cb.state("t") == CircuitBreaker.STATE_OPEN
    assert cb.allow("t") is False

    time.sleep(0.06)
    # The first allow() after cooldown should succeed and move to half_open.
    assert cb.allow("t") is True
    assert cb.state("t") == CircuitBreaker.STATE_HALF_OPEN


def test_half_open_success_closes_circuit() -> None:
    """In half_open, a single success closes the circuit and resets counters."""
    cb = _fresh_breaker(fail_threshold=1, cooldown_seconds=0.05)
    cb.record_failure("t")
    time.sleep(0.06)
    cb.allow("t")  # → half_open
    assert cb.state("t") == CircuitBreaker.STATE_HALF_OPEN
    cb.record_success("t")
    assert cb.state("t") == CircuitBreaker.STATE_CLOSED
    assert cb.allow("t") is True


def test_half_open_failure_reopens_circuit() -> None:
    """In half_open, a failure re-opens the circuit immediately."""
    cb = _fresh_breaker(fail_threshold=1, cooldown_seconds=0.05)
    cb.record_failure("t")
    time.sleep(0.06)
    cb.allow("t")  # → half_open
    assert cb.state("t") == CircuitBreaker.STATE_HALF_OPEN
    cb.record_failure("t")
    assert cb.state("t") == CircuitBreaker.STATE_OPEN
    assert cb.allow("t") is False


def test_failures_across_different_tools_are_isolated() -> None:
    """Per-tool circuit state — tool A's failures do not affect tool B."""
    cb = _fresh_breaker(fail_threshold=1)
    cb.record_failure("a")
    assert cb.state("a") == CircuitBreaker.STATE_OPEN
    # `b` was never touched, must still be closed.
    assert cb.state("b") == CircuitBreaker.STATE_CLOSED
    assert cb.allow("b") is True


def test_failure_window_resets_counter_after_expiry() -> None:
    """If `window_seconds` elapses with no failures, the counter restarts."""
    cb = CircuitBreaker(fail_threshold=2, window_seconds=0.05, cooldown_seconds=1.0)
    cb.record_failure("t")
    time.sleep(0.06)
    cb.record_failure("t")  # first failure in a new window
    # Still only 1 failure in the new window — should be closed.
    assert cb.state("t") == CircuitBreaker.STATE_CLOSED


def test_day2_alias_kwargs_are_accepted() -> None:
    """`failure_threshold` and `reset_timeout_ms` alias the historical names."""
    cb = CircuitBreaker(failure_threshold=4, reset_timeout_ms=250)
    assert cb.fail_threshold == 4
    assert cb.cooldown_seconds == 0.25
    # And the read-only property aliases match.
    assert cb.failure_threshold == 4
    assert cb.reset_timeout_ms == 250


def test_constructor_rejects_invalid_args() -> None:
    """`fail_threshold < 1` and non-positive window/cooldown must raise."""
    with pytest.raises(ValueError):
        CircuitBreaker(fail_threshold=0)
    with pytest.raises(ValueError):
        CircuitBreaker(window_seconds=0)
    with pytest.raises(ValueError):
        CircuitBreaker(cooldown_seconds=0)


def test_module_level_singleton_helpers_round_trip() -> None:
    """The module-level `check_breaker` / `record_*` helpers share one breaker.

    Uses a process-unique sentinel name so it cannot collide with state left
    over from other tests that exercise the singleton.
    """
    name = "test_singleton_helper_xyz_unique"
    # Start from a known-good (closed) state. On a fresh slot `allow()` is
    # already True; `record_success` is a no-op for the state but cheap.
    record_success(name)
    assert check_breaker(name) is True

    # Drive failures well past the default `fail_threshold=5`.
    for _ in range(20):
        record_failure(name)
    assert check_breaker(name) is False

    # Success closes the circuit again.
    record_success(name)
    assert check_breaker(name) is True
