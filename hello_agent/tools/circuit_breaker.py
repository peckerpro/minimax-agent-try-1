"""Per-tool circuit breaker.

After N consecutive failures within `window_seconds`, the circuit "opens" for
`cooldown_seconds`, during which calls are rejected immediately. After cooldown,
the circuit becomes "half-open" — the next call is allowed as a trial; success
closes it, failure re-opens it.
"""
from __future__ import annotations

import time
from threading import Lock


class CircuitBreaker:
    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"

    def __init__(
        self,
        fail_threshold: int = 5,
        window_seconds: float = 60.0,
        cooldown_seconds: float = 30.0,
        *,
        # Day-2 spec names — accepted as keyword-only aliases for the
        # historical parameter names above. Both are equivalent:
        #   - `failure_threshold`  == `fail_threshold`
        #   - `reset_timeout_ms`   == `cooldown_seconds * 1000`
        failure_threshold: int | None = None,
        reset_timeout_ms: int | None = None,
    ) -> None:
        # Apply the day-2 aliases if the historical names weren't given.
        if failure_threshold is not None:
            fail_threshold = failure_threshold
        if reset_timeout_ms is not None:
            cooldown_seconds = reset_timeout_ms / 1000.0

        if fail_threshold < 1:
            raise ValueError("fail_threshold must be >= 1")
        if window_seconds <= 0 or cooldown_seconds <= 0:
            raise ValueError("window/cooldown must be positive")
        self.fail_threshold = fail_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._state: dict[str, dict[str, float | str | int]] = {}
        self._lock = Lock()

    # --- day-2 spec property names (read-only aliases) ---

    @property
    def failure_threshold(self) -> int:
        """Alias for `fail_threshold` (day-2 spec name)."""
        return self.fail_threshold

    @property
    def reset_timeout_ms(self) -> int:
        """Alias for `cooldown_seconds` in milliseconds (day-2 spec name)."""
        return int(self.cooldown_seconds * 1000)

    def _slot(self, tool_name: str) -> dict[str, float | str | int]:
        return self._state.setdefault(
            tool_name,
            {
                "state": self.STATE_CLOSED,
                "failures": 0,
                "first_fail_at": 0.0,
                "opened_at": 0.0,
            },
        )

    def allow(self, tool_name: str) -> bool:
        """Return True if the call should proceed; False if circuit is open."""
        with self._lock:
            slot = self._slot(tool_name)
            state = slot["state"]
            if state == self.STATE_CLOSED:
                return True
            if state == self.STATE_OPEN:
                # Check if cooldown has elapsed → move to half-open
                if time.time() - float(slot["opened_at"]) >= self.cooldown_seconds:
                    slot["state"] = self.STATE_HALF_OPEN
                    return True
                return False
            # half_open: allow exactly one trial
            return True

    def record_success(self, tool_name: str) -> None:
        with self._lock:
            slot = self._slot(tool_name)
            slot["state"] = self.STATE_CLOSED
            slot["failures"] = 0
            slot["first_fail_at"] = 0.0
            slot["opened_at"] = 0.0

    def record_failure(self, tool_name: str) -> None:
        with self._lock:
            slot = self._slot(tool_name)
            now = time.time()
            if slot["state"] == self.STATE_HALF_OPEN:
                # Trial failed → re-open
                slot["state"] = self.STATE_OPEN
                slot["opened_at"] = now
                return

            if int(slot["failures"]) == 0 or now - float(slot["first_fail_at"]) > self.window_seconds:
                # Window expired — restart counting
                slot["first_fail_at"] = now
                slot["failures"] = 1
            else:
                slot["failures"] = int(slot["failures"]) + 1

            if int(slot["failures"]) >= self.fail_threshold:
                slot["state"] = self.STATE_OPEN
                slot["opened_at"] = now

    def state(self, tool_name: str) -> str:
        with self._lock:
            return str(self._slot(tool_name)["state"])


# Module-level singleton breaker.
_breaker = CircuitBreaker()


def check_breaker(tool_name: str) -> bool:
    return _breaker.allow(tool_name)


def record_success(tool_name: str) -> None:
    _breaker.record_success(tool_name)


def record_failure(tool_name: str) -> None:
    _breaker.record_failure(tool_name)


def breaker_state(tool_name: str) -> str:
    return _breaker.state(tool_name)
