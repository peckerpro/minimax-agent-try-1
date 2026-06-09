"""Windows autostart helper — write/read/delete the HKCU\\...\\Run entry.

The autostart entry is a single value under:
    HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
    Value name: hello-agent
    Value data: uv --directory <repo> run hello-agent serve --no-tray

This is per-user (HKCU, not HKLM) so it doesn't require admin rights.
The tray is explicitly disabled with --no-tray because the autostart
session has no graphical desktop to show a tray on reliably.

On non-Windows platforms, the public functions raise
`AutostartUnsupportedError`. The module itself imports cleanly so the
test suite can load it on any platform.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from hello_agent.core.logging import get_logger

logger = get_logger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "hello-agent"


class AutostartError(Exception):
    """Base error for autostart operations."""


class AutostartUnsupportedError(AutostartError, NotImplementedError):
    """Raised when autostart is invoked on a non-Windows platform."""


@dataclass(frozen=True)
class AutostartEntry:
    """In-memory representation of the registry entry."""

    name: str
    command: str


def _build_command(repo_root: str) -> str:
    """Return the shell command that boots hello-agent on logon.

    `uv --directory <repo> run hello-agent serve --no-tray` keeps the
    tray out of the way (logon session has no interactive desktop on
    most Windows SKUs). The trailing quotes are required so `uv`
    correctly resolves the path even if it contains spaces.
    """
    return f'uv --directory "{repo_root}" run hello-agent serve --no-tray'


def _is_windows() -> bool:
    return os.name == "nt"


def enable_autostart(repo_root: str | None = None) -> bool:
    """Write the autostart registry entry. Returns True on success.

    `repo_root` defaults to the parent of `$HELLO_AGENT_HOME`, which is
    where the project clone lives in a normal install. The function
    is idempotent: a second call simply rewrites the same value.
    """
    if not _is_windows():
        raise AutostartUnsupportedError(
            "autostart is Windows-only (HKCU\\...\\Run); "
            f"current platform: {sys.platform}",
        )

    import winreg  # type: ignore[import-not-found]  # Windows-only

    if repo_root is None:
        # Walk up from $HELLO_AGENT_HOME to the project root (the directory
        # that contains pyproject.toml). Best-effort: fall back to the
        # parent of the home dir if the lookup fails.
        try:
            from hello_agent.core.paths import get_hello_agent_home

            home = get_hello_agent_home()
            # home is typically <repo>/profiles/<profile> or <repo> itself.
            candidate = home.parent
            # If the home is already at repo root, this is the repo.
            repo_root = str(candidate)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not resolve repo_root: {}", exc)
            repo_root = "."

    cmd = _build_command(repo_root)

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
    except OSError as exc:
        logger.error("failed to enable autostart: {}", exc)
        return False

    logger.info("autostart enabled: {} -> {}", APP_NAME, cmd)
    return True


def disable_autostart() -> bool:
    """Delete the autostart registry entry. Idempotent (missing = True).

    Returns True on success or when the entry wasn't present. False on
    an unexpected registry error.
    """
    if not _is_windows():
        raise AutostartUnsupportedError(
            "autostart is Windows-only (HKCU\\...\\Run); "
            f"current platform: {sys.platform}",
        )

    import winreg  # type: ignore[import-not-found]  # Windows-only

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        # Entry wasn't set — idempotent success.
        return True
    except OSError as exc:
        logger.error("failed to disable autostart: {}", exc)
        return False

    logger.info("autostart disabled: {}", APP_NAME)
    return True


def is_autostart_enabled() -> bool:
    """Return True if the autostart entry is present and readable."""
    if not _is_windows():
        raise AutostartUnsupportedError(
            "autostart is Windows-only (HKCU\\...\\Run); "
            f"current platform: {sys.platform}",
        )

    import winreg  # type: ignore[import-not-found]  # Windows-only

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
        return bool(value)
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("autostart probe failed: {}", exc)
        return False


def get_autostart_entry() -> AutostartEntry | None:
    """Return the current autostart entry, or None if not present.

    Useful for `hello-agent autostart status` to print what is actually
    registered (the user can verify the command path is still valid).
    """
    if not _is_windows():
        raise AutostartUnsupportedError(
            "autostart is Windows-only (HKCU\\...\\Run); "
            f"current platform: {sys.platform}",
        )

    import winreg  # type: ignore[import-not-found]  # Windows-only

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("autostart read failed: {}", exc)
        return None
    return AutostartEntry(name=APP_NAME, command=str(value))


__all__ = [
    "enable_autostart",
    "disable_autostart",
    "is_autostart_enabled",
    "get_autostart_entry",
    "AutostartEntry",
    "AutostartError",
    "AutostartUnsupportedError",
    "RUN_KEY",
    "APP_NAME",
]