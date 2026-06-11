"""Backend lifecycle manager for the desktop GUI.

The desktop GUI is one process. The FastAPI backend is another
process (started via `hello-agent serve --no-tray`). This module:

- Starts the backend as a subprocess if it's not already running
  (checks the configured port first)
- Tracks the subprocess PID so we can shut it down on Quit
- Falls back gracefully if the user wants to point at an existing
  backend (e.g. one they started manually)

Process model:

    +---------------------+        +-------------------------+
    |  desktop (this)     | -----> |  backend subprocess     |
    |  - pywebview window |  HTTP  |  - FastAPI / uvicorn    |
    |  - pystray icon     |        |  - no tray              |
    |  - backend manager  | <----- |  (we spawned it)        |
    +---------------------+  kill  +-------------------------+

If the user already has a backend running on the port, the desktop
just connects to it; no subprocess is spawned. We never kill a
backend we didn't start.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from hello_agent.core.logging import get_logger

logger = get_logger(__name__)


def _port_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """True iff something is accepting TCP on (host, port)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def wait_for_backend(
    host: str, port: int, *, timeout_s: float = 30.0, poll_s: float = 0.3
) -> bool:
    """Block until the backend is listening on (host, port) or the timeout elapses.

    Returns True if the backend came up, False on timeout. Used after
    spawning a backend subprocess to wait for FastAPI to be ready
    before opening the webview.

    The default 30s is generous because Windows + cold `uv run` +
    `import fastapi` can take 5-10s on a slow machine, and we want
    the webview to open with a working backend on the first try.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _port_listening(host, port):
            return True
        time.sleep(poll_s)
    return False


class BackendManager:
    """Lifecycle owner for a `hello-agent serve --no-tray` subprocess.

    Use `ensure_running()` to get a backend on the configured port
    (spawning one if none exists). Use `shutdown()` to stop a backend
    we started; pass `own=False` to leave a pre-existing backend alone.
    """

    def __init__(self, host: str, port: int, *, workdir: Path) -> None:
        self.host = host
        self.port = port
        self.workdir = workdir
        self._proc: subprocess.Popen[bytes] | None = None
        self._own_proc: bool = False  # True iff we spawned the subprocess

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def is_listening(self) -> bool:
        return _port_listening(self.host, self.port)

    def ensure_running(self) -> bool:
        """Make sure a backend is listening on the configured port.

        Returns True if a backend is available when this returns
        (either pre-existing or just-spawned). Returns False if we
        tried to spawn and the port didn't open within the timeout.
        """
        if self.is_listening():
            logger.info(
                "backend already listening on {} (will not spawn)", self.url
            )
            self._own_proc = False
            return True

        if not self._spawn():
            return False
        return self.is_listening()

    def _spawn(self) -> bool:
        """Spawn `hello-agent serve --no-tray` as a subprocess.

        Returns True if the subprocess launched (does NOT guarantee
        the backend is listening yet — call `wait_for_backend`).
        """
        # Use the same Python interpreter that's running us; that way
        # we inherit the user's activated venv / uv environment.
        cmd = [
            sys.executable,
            "-m",
            "hello_agent.cli.main",
            "serve",
            "serve",
            "--no-tray",
            "--no-open",
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]
        logger.info("spawning backend: {}", " ".join(cmd))
        # On Windows, CREATE_NEW_PROCESS_GROUP lets us send CTRL_BREAK_EVENT
        # to the child for graceful shutdown. Detached so the child
        # doesn't get a console flash on Windows.
        kwargs: dict[str, Any] = {
            "cwd": str(self.workdir),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
            )

        try:
            self._proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603
        except OSError as exc:
            logger.error("failed to spawn backend: {}", exc)
            return False

        self._own_proc = True
        logger.info("backend spawned, pid={}", self._proc.pid)
        return True

    def shutdown(self, *, timeout_s: float = 5.0) -> None:
        """Stop the backend if (and only if) we spawned it.

        Calling this on a backend we didn't own is a no-op — the user
        keeps their manually-started server.
        """
        if not self._own_proc or self._proc is None:
            logger.debug("shutdown: not owning the backend, leaving it alone")
            return
        if self._proc.poll() is not None:
            # Already exited; reap and reset state.
            self._proc = None
            self._own_proc = False
            return

        logger.info("shutting down backend pid={}", self._proc.pid)
        try:
            if os.name == "nt":
                # Graceful: send CTRL_BREAK_EVENT. Subprocess must have
                # been created with CREATE_NEW_PROCESS_GROUP for this
                # to work.
                self._proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                logger.warning("backend did not exit gracefully; killing")
                self._proc.kill()
                self._proc.wait(timeout=2.0)
        except OSError as exc:
            logger.warning("backend shutdown raised: {}", exc)
        finally:
            self._proc = None
            self._own_proc = False


__all__ = ["BackendManager", "wait_for_backend"]
