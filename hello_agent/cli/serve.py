"""`hello-agent serve` 鈥?start FastAPI server + optional tray."""
from __future__ import annotations

import os
import signal
import threading

import typer

from hello_agent.core.config import get_env
from hello_agent.core.logging import get_logger

app = typer.Typer(help="Run the Web UI server (and optional tray).")
logger = get_logger(__name__)

_shutdown_event: threading.Event | None = None


def request_shutdown() -> None:
    """Signal the server to shut down (used by tray 'Quit')."""
    if _shutdown_event is not None:
        _shutdown_event.set()


@app.command(name="serve")
def serve(
    host: str | None = typer.Option(None, "--host", "-h"),
    port: int | None = typer.Option(None, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev only)."),
    no_tray: bool = typer.Option(False, "--no-tray", help="Skip the system tray icon."),
    open_browser: bool | None = typer.Option(None, "--open/--no-open"),
) -> None:
    """Start the FastAPI server and (on Windows) the tray icon."""
    global _shutdown_event
    env = get_env()
    host = host or env.web_host
    port = port or env.web_port
    if open_browser is None:
        open_browser = env.web_open_browser_on_start

    try:
        import uvicorn  # type: ignore[import-not-found]
    except ImportError as exc:
        typer.echo(f"web extras not installed: {exc}\n  鈫?uv sync --extra web", err=True)
        raise typer.Exit(code=1) from exc

    try:
        from hello_agent.web.server import create_app
    except ImportError as exc:
        typer.echo(f"failed to import web server: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if open_browser:
        import webbrowser
        from threading import Timer

        def _open() -> None:
            try:
                webbrowser.open(f"http://{host}:{port}")
            except Exception:  # noqa: BLE001
                pass

        Timer(1.5, _open).start()

    if not no_tray and os.name == "nt":
        try:
            from hello_agent.windows.tray import start_tray

            start_tray(port)
        except Exception as exc:  # noqa: BLE001
            logger.warning("tray failed to start: {}", exc)

    _shutdown_event = threading.Event()

    def _on_signal(signum, frame):  # noqa: ARG001
        if _shutdown_event is not None:
            _shutdown_event.set()

    try:
        signal.signal(signal.SIGINT, _on_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _on_signal)
    except (ValueError, OSError):
        pass  # not main thread, or unsupported (e.g. Windows + non-console)

    typer.echo(f"hello-agent Web UI starting on http://{host}:{port}")

    fastapi_app = create_app()
    config = uvicorn.Config(fastapi_app, host=host, port=port, log_level="info", reload=reload)
    server = uvicorn.Server(config)

    # Run server in main thread; shutdown event will be signalled by tray.
    try:
        server.run()
    except KeyboardInterrupt:
        typer.echo("\nshutting down...")


if __name__ == "__main__":
    app()
