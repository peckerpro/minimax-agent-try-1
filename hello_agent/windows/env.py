"""Environment probe for `hello-agent doctor`.

`probe_env()` returns a dict describing the runtime environment:
- python_version       str     (e.g. "3.11.9")
- python_executable    str     (absolute path)
- uv_version           str|None
- platform             str     ("Windows", "Linux", "Darwin")
- platform_version     str|None
- llm_api_key_set      bool    (truthy if env.llm_api_key is non-empty and not the default placeholder)
- llm_base_url         str
- home_dir             str
- network_reachable    bool    (TCP probe to env.llm_base_url host)
- web_extras           bool    (fastapi/uvicorn installed)
- windows_extras       bool    (pystray/pywin32 installed)

The function never raises — every probe is wrapped in a try/except and
returns a sentinel (None / False) on failure. `hello-agent doctor`
consumes this dict to render its checklist.

Cross-platform safe: works on Windows, Linux, macOS.
"""
from __future__ import annotations

import importlib.util
import os
import platform as _platform
import shutil
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from hello_agent.core.config import get_env  # noqa: F401 — re-exported for back-compat
from hello_agent.core.logging import get_logger

logger = get_logger(__name__)


def _probe_python_version() -> str:
    return _platform.python_version()


def _probe_python_executable() -> str:
    return sys.executable


def _probe_uv_version() -> str | None:
    uv = shutil.which("uv")
    if uv is None:
        return None
    try:
        import subprocess

        out = subprocess.run(  # noqa: S603
            [uv, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        # `uv --version` prints e.g. "uv 0.4.7 (abcdef0 2024-12-12)"
        first_line = (out.stdout or "").strip().splitlines()[0] if out.stdout else ""
        # Normalize to just the version string (e.g. "0.4.7").
        parts = first_line.split()
        if len(parts) >= 2 and parts[0] == "uv":
            return parts[1]
        return first_line or None
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("uv --version probe failed: {}", exc)
        return None


def _probe_platform() -> str:
    return _platform.system()


def _probe_platform_version() -> str | None:
    try:
        return _platform.version()
    except OSError:
        return None


def _probe_llm_api_key_set() -> bool:
    # Use dynamic attribute access so tests can monkeypatch
    # `hello_agent.core.config.get_env` to simulate a config failure.
    from hello_agent.core import config as _config_mod

    try:
        env = _config_mod.get_env()
    except Exception as exc:  # noqa: BLE001 — config not yet loaded
        logger.debug("get_env() failed during probe: {}", exc)
        return False
    key = (env.llm_api_key or "").strip()
    return bool(key) and key != "sk-replace-me"


def _probe_llm_base_url() -> str:
    from hello_agent.core import config as _config_mod

    try:
        env = _config_mod.get_env()
    except Exception:  # noqa: BLE001
        return ""
    return env.llm_base_url or ""


def _probe_home_dir() -> str:
    try:
        from hello_agent.core.paths import display_hello_agent_home

        return display_hello_agent_home()
    except Exception:  # noqa: BLE001
        return str(Path.cwd())


def _probe_network(base_url: str, timeout: float = 5.0) -> bool:
    """TCP-probe the LLM provider. Returns False on any failure."""
    if not base_url:
        return False
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError) as exc:
        logger.debug("network probe to {}:{} failed: {}", host, port, exc)
        return False


def _extras_installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _probe_web_extras() -> bool:
    return _extras_installed("fastapi") and _extras_installed("uvicorn")


def _probe_windows_extras() -> bool:
    if os.name != "nt":
        # pystray on macOS works for some users, but our v0.2 contract is
        # Windows-only. Treat as "not installed" so the doctor hint says
        # install --extra windows when on macOS/Linux.
        return _extras_installed("pystray")
    return _extras_installed("pystray") and _extras_installed("win32")


def probe_env() -> dict[str, Any]:
    """Run all probes and return a dict of results.

    The function is intentionally non-raising — every probe has its own
    try/except so doctor.py can render the full picture even when one
    probe fails.
    """
    base_url = _probe_llm_base_url()
    return {
        "python_version": _probe_python_version(),
        "python_executable": _probe_python_executable(),
        "uv_version": _probe_uv_version(),
        "platform": _probe_platform(),
        "platform_version": _probe_platform_version(),
        "llm_api_key_set": _probe_llm_api_key_set(),
        "llm_base_url": base_url,
        "home_dir": _probe_home_dir(),
        "network_reachable": _probe_network(base_url),
        "web_extras": _probe_web_extras(),
        "windows_extras": _probe_windows_extras(),
    }


__all__ = ["probe_env"]