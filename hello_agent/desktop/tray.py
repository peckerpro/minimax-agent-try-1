"""Desktop-side system tray icon.

The desktop process owns its own tray (separate from the tray in
`hello_agent.windows.tray`, which is the tray the backend process
owns). The desktop tray is about CONTROLLING THE WINDOW, not the
backend's lifecycle.

Menu:
  - Show / hide the webview window
  - Open in browser (alternative window)
  - Run doctor (opens a terminal running `hello-agent doctor`)
  - Quit (closes the window + shuts down the backend if we own it)

The tray runs in a daemon thread alongside the webview's main
thread. Both exit cleanly when the user picks Quit.
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from typing import TYPE_CHECKING, Any

from hello_agent.core.logging import get_logger

if TYPE_CHECKING:
    from PIL import Image
    from pystray import Icon

logger = get_logger(__name__)


def _load_icon_image() -> Image.Image | None:
    """Reuse the asset shipped in `hello_agent/assets/tray.png`; fall back to nothing.

    Returns None if pystray / Pillow aren't installed; the caller
    (start_desktop_tray) will then skip the tray entirely.
    """
    try:
        from PIL import Image, ImageDraw  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        return None

    from hello_agent.windows.tray import ICON_PATH  # noqa: PLC0415

    if ICON_PATH.is_file():
        try:
            return Image.open(ICON_PATH)  # type: ignore[return-value]
        except OSError as exc:
            logger.warning("failed to load desktop tray icon: {}", exc)

    img = Image.new("RGB", (64, 64), color="white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((8, 8, 56, 56), fill="#1f77b4")
    draw.text((20, 20), "HA", fill="white")
    return img


def start_desktop_tray(
    *,
    url: str,
    on_show: Any,
    on_hide: Any,
    on_quit: Any,
    app_name: str = "hello-agent Desktop",
) -> Icon | None:
    """Spawn the desktop tray icon. Returns the Icon, or None if unavailable.

    Callers must keep the returned Icon alive (a daemon thread holds
    its event loop) and call `icon.stop()` on Quit. The three callbacks
    are the only UI actions the tray exposes.
    """
    try:
        from pystray import Icon, Menu, MenuItem  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        logger.warning(
            "pystray not installed; desktop tray disabled. uv sync --extra windows"
        )
        return None

    image = _load_icon_image()
    if image is None:
        return None

    def _on_open_browser(_icon: Any, _item: Any) -> None:
        try:
            webbrowser.open(url)
        except OSError as exc:
            logger.warning("open-in-browser failed: {}", exc)

    def _on_show_cb(_icon: Any, _item: Any) -> None:
        try:
            on_show()
        except Exception as exc:  # noqa: BLE001
            logger.warning("on_show callback raised: {}", exc)

    def _on_hide_cb(_icon: Any, _item: Any) -> None:
        try:
            on_hide()
        except Exception as exc:  # noqa: BLE001
            logger.warning("on_hide callback raised: {}", exc)

    def _on_quit_cb(icon: Any, _item: Any) -> None:
        try:
            icon.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("tray stop raised: {}", exc)
        try:
            on_quit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("on_quit callback raised: {}", exc)

    menu = Menu(
        MenuItem("Show Window", _on_show_cb, default=True),
        MenuItem("Hide Window", _on_hide_cb),
        MenuItem("Open in Browser", _on_open_browser),
        Menu.SEPARATOR,
        MenuItem("Quit", _on_quit_cb),
    )

    try:
        icon = Icon(app_name, image, app_name, menu)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to construct desktop tray Icon: {}", exc)
        return None

    thread = threading.Thread(target=icon.run, daemon=True, name="hello-agent-desktop-tray")
    thread.start()
    logger.info("desktop tray icon started (pid={})", os.getpid())
    return icon


def stop_tray(icon: Icon | None) -> None:
    """Stop the desktop tray. Safe to call with None or an already-stopped icon."""
    if icon is None:
        return
    try:
        icon.stop()
    except Exception as exc:  # noqa: BLE001
        logger.debug("desktop tray stop raised (benign): {}", exc)


__all__ = ["start_desktop_tray", "stop_tray"]


# Imported lazily so this module stays importable on non-Windows for
# type-checking; the import would also fail in slim CI installs
# without `pystray`.
if sys.platform != "win32":
    pass
