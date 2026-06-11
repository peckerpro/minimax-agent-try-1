"""`hello-agent desktop` — open the React UI in a native webview window.

Process model (see `hello_agent.desktop.backend.BackendManager`):

    +---------------------+        +-------------------------+
    |  desktop (this)     | -----> |  backend subprocess     |
    |  - pywebview window |  HTTP  |  - FastAPI / uvicorn    |
    |  - pystray icon     |        |  - no tray              |
    |  - backend manager  | <----- |  (we spawned it)        |
    +---------------------+  kill  +-------------------------+

The desktop process never imports `hello_agent.web.server`. The
backend is a separate process; both the webview window and the
desktop tray talk to it over HTTP.

Usage:
    uv run hello-agent desktop                # auto: spawn backend if needed
    uv run hello-agent desktop --no-spawn     # assume backend is already running
    uv run hello-agent desktop --port 9000    # use a different port
    uv run hello-agent desktop --no-tray      # no desktop tray
"""
from __future__ import annotations

import sys
from pathlib import Path

import typer

from hello_agent.core.config import get_env
from hello_agent.core.logging import get_logger

app = typer.Typer(
    help="Open the Web UI in a native desktop window (pywebview).",
    no_args_is_help=True,
)
logger = get_logger(__name__)


def _resolve_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _resolve_workdir() -> Path:
    """Best-effort guess at the project root for spawning the backend.

    Falls back to the current working directory. The user can `cd`
    into the project before running, or we just spawn with the
    `python -m` module path which works regardless of cwd as long
    as the package is importable.
    """
    return Path.cwd()


def _do_open(
    host: str | None,
    port: int | None,
    no_spawn: bool,
    no_tray: bool,
    title: str | None,
    width: int | None,
    height: int | None,
) -> None:
    """Shared implementation for `desktop` (default) and `desktop open`.

    Lifecycle:
      1. Resolve config (host/port from .env if not given).
      2. Ensure backend is running — spawn it ourselves if not.
      3. Open the webview window (blocks on main thread).
      4. On any exit path, reap the backend we spawned (if we own it)
         and stop the desktop tray.

    The `_tray_ref` is a single-element list because the inner close
    callback (defined in the middle of the function) needs to see
    the tray icon that the outer code creates later. A normal
    variable would be a `UnboundLocalError`; the list is a Python
    idiom for "mutable box that captures the closure".
    """
    env = get_env()
    host = host or env.web_host
    port = port or env.web_port

    # Lazy imports so a non-desktop install (no pywebview / pystray) just
    # gets a clean error message instead of a stack trace at import time.
    from hello_agent.desktop import webview as dw
    from hello_agent.desktop.backend import BackendManager
    from hello_agent.desktop.tray import start_desktop_tray, stop_tray

    if not dw.is_available():
        typer.echo(
            "pywebview is not installed. Run:  uv sync --extra desktop",
            err=True,
        )
        raise typer.Exit(code=1)

    url = _resolve_url(host, port)
    typer.echo(f"hello-agent desktop → {url}")

    # 1. Ensure backend is up. mgr is held in try/finally so we always
    #    reap a backend we spawned, even if ensure_running() raises.
    mgr = BackendManager(host=host, port=port, workdir=_resolve_workdir())
    _tray_ref: list = [None]  # filled in by step 4; read by close hook
    try:
        if no_spawn:
            if not mgr.is_listening():
                typer.echo(
                    f"--no-spawn set but nothing is listening on {url}. "
                    f"Start the backend first:  uv run hello-agent serve serve --no-tray",
                    err=True,
                )
                raise typer.Exit(code=1)
        else:
            typer.echo("ensuring backend is running…")
            if not mgr.ensure_running():
                typer.echo(
                    f"failed to start backend on {url} within timeout. "
                    f"Check `uv run hello-agent doctor` and try `--no-spawn` "
                    f"if the backend is already running.",
                    err=True,
                )
                raise typer.Exit(code=1)
            typer.echo(f"backend up at {url}")

        # 2. Close hook (window close → maybe-shutdown backend).
        def _on_window_closed() -> None:
            mgr.shutdown()
            stop_tray(_tray_ref[0])

        # 3. Tray runs in a daemon thread; the webview runs on the main thread.
        if not no_tray:
            # Show/hide are no-ops on plain pywebview (no `hide` API), but
            # the tray still serves as a Quit shortcut and "open in browser"
            # convenience.
            def _show() -> None:
                typer.echo(
                    "(tray) showing window — close-and-reopen if it's behind something"
                )

            def _hide() -> None:
                typer.echo(
                    "(tray) hide is not supported in the current pywebview; "
                    "close the window instead"
                )

            def _quit() -> None:
                logger.info("tray Quit: closing window and shutting down backend")
                sys.exit(0)

            _tray_ref[0] = start_desktop_tray(
                url=url,
                on_show=_show,
                on_hide=_hide,
                on_quit=_quit,
            )

        # 4. Block on the webview.
        title_final = title or "hello-agent Desktop"
        width_final = width or 1200
        height_final = height or 800
        dw.open_window(
            url,
            title=title_final,
            width=width_final,
            height=height_final,
            on_closed=_on_window_closed,
        )
    finally:
        # Reap backend + stop tray on EVERY exit path:
        #   - user closed the window (normal exit)
        #   - typer.Exit() from a startup failure
        #   - KeyboardInterrupt
        #   - webview crash
        mgr.shutdown()
        stop_tray(_tray_ref[0])


# `hello-agent desktop` (no subcommand) opens the window.
@app.callback(invoke_without_command=True)
def desktop_default(
    ctx: typer.Context,
    host: str | None = typer.Option(None, "--host", "-h", help="Backend host (default: from .env)"),
    port: int | None = typer.Option(None, "--port", "-p", help="Backend port (default: from .env)"),
    no_spawn: bool = typer.Option(
        False,
        "--no-spawn",
        help="Don't spawn the backend; assume it's already running on the port.",
    ),
    no_tray: bool = typer.Option(False, "--no-tray", help="Skip the desktop tray icon."),
    title: str | None = typer.Option(None, "--title", help="Window title (default: 'hello-agent Desktop')"),
    width: int | None = typer.Option(None, "--width", help="Window width"),
    height: int | None = typer.Option(None, "--height", help="Window height"),
) -> None:
    """Open the Web UI in a native desktop window (pywebview)."""
    if ctx.invoked_subcommand is not None:
        return  # a real subcommand was given, don't run the default
    _do_open(
        host=host,
        port=port,
        no_spawn=no_spawn,
        no_tray=no_tray,
        title=title,
        width=width,
        height=height,
    )


@app.command("open")
def desktop_open(
    host: str | None = typer.Option(None, "--host", "-h", help="Backend host (default: from .env)"),
    port: int | None = typer.Option(None, "--port", "-p", help="Backend port (default: from .env)"),
    no_spawn: bool = typer.Option(
        False,
        "--no-spawn",
        help="Don't spawn the backend; assume it's already running on the port.",
    ),
    no_tray: bool = typer.Option(False, "--no-tray", help="Skip the desktop tray icon."),
    title: str | None = typer.Option(None, "--title", help="Window title (default: 'hello-agent Desktop')"),
    width: int | None = typer.Option(None, "--width", help="Window width"),
    height: int | None = typer.Option(None, "--height", help="Window height"),
) -> None:
    """Open the Web UI in a native desktop window (alias of the default)."""
    _do_open(
        host=host,
        port=port,
        no_spawn=no_spawn,
        no_tray=no_tray,
        title=title,
        width=width,
        height=height,
    )


if __name__ == "__main__":
    app()
