"""System tray icon for hello-agent (Windows / pystray).

Exports:
    start_tray(web_port, ...)  — spawn the tray icon in a background thread
    stop_tray(icon)            — stop the icon's event loop (called on Quit)
    _create_icon_image()       — generate the fallback 64x64 RGB icon

Design choices:
- The icon image is loaded from `hello_agent/assets/tray.png` (16x16) when
  available; otherwise a Pillow-generated 64x64 blue square is used. We keep
  the runtime fallback because the asset may be missing in slim installs
  (e.g. a source-only checkout before `npm run build` for the web UI is
  not needed for the tray, but the icon asset is shipped separately).
- The tray runs in a daemon thread so it never blocks process exit if the
  uvicorn loop fails.
- `start_tray` returns the `pystray.Icon` instance so callers (e.g. `cli/serve.py`)
  can call `stop_tray(icon)` on shutdown.
- The Quit menu callback sets the module-level shutdown event used by
  `cli.serve.request_shutdown()` — uvicorn then exits its main loop.

This module is only useful on platforms where pystray has a working
backend (Windows + most Linux DEs). It is a no-op stub on macOS in some
configurations. All public functions therefore catch backend errors and
log a warning rather than crash the serve entry.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hello_agent.core.logging import get_logger

if TYPE_CHECKING:
    from PIL import Image
    from pystray import Icon

logger = get_logger(__name__)

ASSETS_DIR: Path = Path(__file__).resolve().parent.parent / "assets"
ICON_PATH: Path = ASSETS_DIR / "tray.png"
APP_NAME = "hello-agent"

# Module-level state used by the Quit menu callback.
_shutdown_callback: Any = None  # set by set_shutdown_callback()


def set_shutdown_callback(cb: Any) -> None:
    """Register a callable the tray will invoke when the user clicks Quit.

    `cli/serve.py` registers `request_shutdown` here so the tray can
    signal uvicorn to stop without importing the CLI module at import
    time (which would create a circular import on some platforms).
    """
    global _shutdown_callback
    _shutdown_callback = cb


def _load_icon_image() -> Image.Image:
    """Return the icon image: prefer the shipped PNG; fall back to Pillow-generated.

    The Pillow fallback is intentionally procedural so the tray works
    even if the asset is missing (e.g. slim CI install, dev checkout
    before asset generation).
    """
    from PIL import Image, ImageDraw  # type: ignore[import-not-found]

    if ICON_PATH.is_file():
        try:
            return Image.open(ICON_PATH)  # type: ignore[return-value]
        except OSError as exc:
            logger.warning("failed to load tray icon {}: {}", ICON_PATH, exc)

    img = Image.new("RGB", (64, 64), color="white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((8, 8, 56, 56), fill="#1f77b4")
    draw.text((20, 20), "HA", fill="white")
    return img


def _open_web(port: int, new_chat: bool = False) -> None:
    """Open the Web UI in the user's default browser."""
    url = f"http://127.0.0.1:{port}"
    if new_chat:
        url += "/?new=1"
    try:
        webbrowser.open(url)
    except OSError as exc:
        logger.warning("failed to open web UI: {}", exc)


def _run_doctor_terminal() -> None:
    """Open a new terminal window running `hello-agent doctor`.

    Best-effort: on Windows, we use `cmd /c start cmd /k ...` to spawn
    a console. On other platforms, we fall back to `x-terminal-emulator`
    (Debian/Ubuntu) or `gnome-terminal`. Failures are logged, not raised.
    """
    cmd = [sys.executable, "-m", "hello_agent.cli.main", "doctor"]
    try:
        if sys.platform == "win32":
            subprocess.Popen(  # noqa: S603, S607 — best-effort spawn
                ["cmd", "/c", "start", "cmd", "/k"] + cmd,
                shell=False,
            )
        else:
            for term in ("x-terminal-emulator", "gnome-terminal", "konsole"):
                if _which(term):
                    subprocess.Popen(  # noqa: S603, S607
                        [term, "--"] + cmd,
                        shell=False,
                    )
                    return
            logger.warning("no terminal emulator found; run `hello-agent doctor` manually")
    except OSError as exc:
        logger.warning("failed to spawn doctor terminal: {}", exc)


def _which(cmd: str) -> str | None:
    """Tiny shutil.which wrapper (kept inline to avoid pulling in shutil at module top)."""
    import shutil

    return shutil.which(cmd)


def start_tray(
    web_port: int,
    *,
    app_name: str = APP_NAME,
    on_shutdown: Any = None,
) -> Icon | None:
    """Spawn the system tray icon in a background daemon thread.

    Returns the `pystray.Icon` instance on success, or None if pystray
    is unavailable / the backend fails to initialize. Callers should
    keep the return value so they can call `stop_tray(icon)` later.
    """
    try:
        from pystray import Icon, Menu, MenuItem  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("pystray not installed; tray disabled.  uv sync --extra windows")
        return None

    # Allow callers to override the shutdown callback (for tests).
    if on_shutdown is not None:
        set_shutdown_callback(on_shutdown)

    def on_open_web(_icon: Any, _item: Any) -> None:
        _open_web(web_port)

    def on_new_chat(_icon: Any, _item: Any) -> None:
        _open_web(web_port, new_chat=True)

    def on_doctor(_icon: Any, _item: Any) -> None:
        _run_doctor_terminal()

    def on_quit(icon: Any, _item: Any) -> None:
        try:
            icon.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("tray icon.stop() raised: {}", exc)
        if _shutdown_callback is not None:
            try:
                _shutdown_callback()
            except Exception as exc:  # noqa: BLE001
                logger.warning("shutdown callback raised: {}", exc)

    menu = Menu(
        MenuItem("Open Web UI", on_open_web, default=True),
        MenuItem("New Chat", on_new_chat),
        Menu.SEPARATOR,
        MenuItem("Run Doctor", on_doctor),
        Menu.SEPARATOR,
        MenuItem("Quit", on_quit),
    )

    try:
        icon = Icon(app_name, _load_icon_image(), app_name, menu)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to construct tray Icon: {}", exc)
        return None

    thread = threading.Thread(target=icon.run, daemon=True, name="hello-agent-tray")
    try:
        thread.start()
    except RuntimeError as exc:
        logger.warning("failed to start tray thread: {}", exc)
        return None

    logger.info("system tray icon started (port={}, pid={})", web_port, os.getpid())
    return icon


def stop_tray(icon: Icon | None) -> None:
    """Stop the tray icon's event loop. Safe to call with None or a stopped icon."""
    if icon is None:
        return
    try:
        icon.stop()
    except Exception as exc:  # noqa: BLE001
        logger.debug("tray stop raised (benign): {}", exc)


__all__ = [
    "start_tray",
    "stop_tray",
    "set_shutdown_callback",
    "ICON_PATH",
    "ASSETS_DIR",
    "APP_NAME",
]