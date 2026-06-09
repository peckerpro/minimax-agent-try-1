"""Global hotkey registration (stretch goal — keyboard library).

This module is OPTIONAL: v0.2 ships a working `serve` even when the
`keyboard` package isn't installed. The hotkey is registered only when
the user explicitly passes a non-empty `--hotkey` flag to `serve`.

Why lazy-import:
- The `keyboard` package pulls in platform-specific system hooks
  (Windows: RegisterHotKey; Linux: X11 keybindings). On Windows it
  requires admin / accessibility permissions, which a CI runner or
  a first-time install doesn't have.
- We want `hello-agent serve` to boot without it on headless boxes.

Public surface:
    register_hotkey(combo, callback) -> Optional[Hook]
        Register a global hotkey; returns the underlying keyboard
        hook on success, or None if `keyboard` is unavailable.
    unregister_hotkey(hook) -> bool
        Unregister a previously-registered hook. Returns True on
        success, False on any failure.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hello_agent.core.logging import get_logger

logger = get_logger(__name__)

_KEYBOARD_IMPORT_ERROR: Exception | None = None


def _try_import_keyboard() -> Any | None:
    """Import `keyboard` lazily; cache the result (or failure) at module level."""
    global _KEYBOARD_IMPORT_ERROR
    try:
        import keyboard  # type: ignore[import-not-found]

        return keyboard
    except ImportError as exc:
        _KEYBOARD_IMPORT_ERROR = exc
        return None


def is_available() -> bool:
    """Return True if the `keyboard` package can be imported."""
    return _try_import_keyboard() is not None


def register_hotkey(
    combo: str,
    callback: Callable[[], Any],
) -> Any | None:
    """Register a global hotkey `combo` (e.g. `ctrl+alt+h`).

    On success returns the underlying hook object returned by
    `keyboard.add_hotkey`. On failure (missing module, OS refuses the
    hook, etc.) returns None and logs a warning.

    The callback must take zero positional arguments. Wrap any
    argument-needing callable in a `lambda`.
    """
    keyboard = _try_import_keyboard()
    if keyboard is None:
        logger.warning(
            "keyboard library not installed; global hotkey disabled.  "
            "uv pip install keyboard",
        )
        return None

    try:
        hook = keyboard.add_hotkey(combo, callback, suppress=False)
        logger.info("global hotkey registered: {}", combo)
        return hook
    except (ValueError, OSError) as exc:
        logger.warning("failed to register hotkey {!r}: {}", combo, exc)
        return None


def unregister_hotkey(hook: Any | None) -> bool:
    """Unregister a hotkey previously returned by `register_hotkey`.

    Returns True on success, False on any failure (including
    unregistering a None hook).
    """
    if hook is None:
        return False
    keyboard = _try_import_keyboard()
    if keyboard is None:
        return False
    try:
        keyboard.remove_hotkey(hook)
        return True
    except (ValueError, OSError) as exc:  # noqa: PERF203
        logger.debug("unregister_hotkey raised (benign): {}", exc)
        return False


__all__ = [
    "is_available",
    "register_hotkey",
    "unregister_hotkey",
]