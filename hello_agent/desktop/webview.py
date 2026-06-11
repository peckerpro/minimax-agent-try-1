"""Webview window wrapper for the desktop GUI.

Wraps `webview` (pywebview) so the same React UI served by
`hello_agent/web/server.py` opens in a native OS window. The backend
is owned by a separate process — this module never imports
`hello_agent.web.server` directly. It just points pywebview at the
HTTP URL.

Why pywebview:
- Lightweight: ~5 MB wheel, no Chromium bundling on Windows (uses
  WebView2 / Edge runtime, already installed on Win10/11)
- Cross-platform: works on macOS (WebKit) and Linux (GTK WebKit)
  if/when the user moves the project off Windows
- Native window: titlebar, taskbar, always-on-top, system DPI — all
  free; we'd have to rebuild them for raw Qt/Tk

What this module does NOT do:
- Does not start the FastAPI backend. The CLI (`cli/desktop.py`)
  starts `hello-agent serve --no-tray` as a subprocess first.
- Does not own the tray icon — that's `desktop/tray.py`.
- Does not manage uvicorn shutdown on window close — the user can
  close the webview without killing the backend (other consumers
  like the browser may still be using it).
"""
from __future__ import annotations

import threading
from typing import Any

from hello_agent.core.logging import get_logger

logger = get_logger(__name__)

APP_NAME = "hello-agent"
DEFAULT_TITLE = "hello-agent Desktop"
DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800


def _check_webview() -> None:
    """Raise a clear error if `webview` isn't installed.

    `pywebview` is in the `[desktop]` optional extra. The user gets
    a hint about the right `uv sync` command.
    """
    try:
        import webview  # type: ignore[import-not-found]  # noqa: F401,PLC0415
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pywebview is required for the desktop GUI. "
            "Install with:  uv sync --extra desktop"
        ) from exc


def is_available() -> bool:
    """True iff pywebview is importable. Used by CLI to print a clean error."""
    try:
        import webview  # type: ignore[import-not-found]  # noqa: F401,PLC0415
    except ImportError:
        return False
    return True


def open_window(
    url: str,
    *,
    title: str = DEFAULT_TITLE,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    on_closed: Any = None,
) -> int:
    """Open a native webview window pointing at `url`. Blocks until the window closes.

    Returns the pywebview window's exit code (0 on normal close, nonzero
    on error). The caller is responsible for any backend lifecycle.

    The `on_closed` callback (if provided) is invoked AFTER the user
    closes the window but BEFORE this function returns. Use it to
    trigger backend shutdown if you want one-shot behavior.
    """
    _check_webview()
    import webview  # type: ignore[import-not-found]  # noqa: PLC0415

    logger.info("opening webview window: title={!r} url={} {}x{}", title, url, width, height)

    window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        # Pin to primary screen, not multi-monitor edge cases. The
        # user can drag it anywhere once open.
        x=None,
        y=None,
        resizable=True,
        fullscreen=False,
        # Min size so the React layout doesn't break if the user
        # tries to drag the corner too small.
        min_size=(640, 480),
        # text_select=True keeps the chat history copyable. Confirm/
        # close on Esc are intentionally off — chat UIs don't usually
        # want accidental close on Esc.
        confirm_close=False,
        background_color="#ffffff",
    )

    if on_closed is not None:
        # pywebview fires `closed` events on the window; we forward
        # them to the caller. pywebview 4.x+ exposes this as
        # `window.events.closed += cb`.
        try:
            window.events.closed += on_closed  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — best-effort; older pywebview
            logger.debug("pywebview closed-event hook failed (benign on older versions)")

    # `start()` blocks the calling thread. We don't bother running
    # it in a thread; the CLI invokes this from the main thread.
    webview.start()
    return 0


def open_window_in_thread(
    url: str,
    *,
    title: str = DEFAULT_TITLE,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> tuple[threading.Thread, threading.Event]:
    """Open a webview window in a background thread; return (thread, ready_event).

    Use this when you want the main thread free (e.g. to run a tray
    icon alongside the window). The `ready_event` is set after the
    window is created and visible; the thread runs the pywebview
    event loop until the user closes the window.
    """
    _check_webview()
    ready = threading.Event()

    def _run() -> None:
        try:
            open_window(url, title=title, width=width, height=height)
        except Exception as exc:  # noqa: BLE001
            logger.error("webview window crashed: {}", exc)
        finally:
            ready.set()

    thread = threading.Thread(target=_run, daemon=True, name="hello-agent-webview")
    thread.start()
    return thread, ready


__all__ = [
    "APP_NAME",
    "DEFAULT_TITLE",
    "DEFAULT_WIDTH",
    "DEFAULT_HEIGHT",
    "is_available",
    "open_window",
    "open_window_in_thread",
]
