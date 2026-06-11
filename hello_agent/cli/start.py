"""`hello-agent start` — one-command launcher (the `hermes` / `openclaw` style).

The intuition: instead of remembering which exact command does what,
the user just types `hello-agent start` and gets a working session.
This is the entry point we promise the user in the docs / README.

Modes (configurable; auto-detected by default):

  - `web`       — open the Web UI in the default browser + tray
                  (uses the existing `hello-agent serve` flow; no
                  desktop window)
  - `desktop`   — open the Web UI in a native pywebview window +
                  desktop tray (uses the new `hello-agent desktop`
                  flow)
  - `auto`      — `desktop` if pywebview is installed, else `web`

The chosen mode is persisted to `~/.hello-agent/start_mode` so the
next `hello-agent start` uses the same mode. Override with `--mode`.

Usage:
    uv run hello-agent start                # last-used mode
    uv run hello-agent start --mode web     # force web
    uv run hello-agent start --mode desktop # force desktop
    uv run hello-agent start --mode chat    # drop into the REPL
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer

from hello_agent.core.logging import get_logger

app = typer.Typer(
    help="One-command launcher (web UI / desktop window / chat REPL).",
    invoke_without_command=True,
    no_args_is_help=True,
)
logger = get_logger(__name__)

START_MODE_FILE = "start_mode"  # under $HELLO_AGENT_HOME
VALID_MODES = ("auto", "web", "desktop", "chat")


def _mode_file() -> Path:
    from hello_agent.core.paths import get_hello_agent_home

    return get_hello_agent_home() / START_MODE_FILE


def _read_mode() -> str:
    p = _mode_file()
    if p.is_file():
        try:
            mode = p.read_text(encoding="utf-8").strip()
        except OSError:
            return "auto"
        if mode in VALID_MODES:
            return mode
    return "auto"


def _write_mode(mode: str) -> None:
    p = _mode_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(mode, encoding="utf-8")


def _detect_mode() -> str:
    """Return `desktop` if pywebview is importable, else `web`."""
    try:
        import webview  # type: ignore[import-not-found]  # noqa: F401,PLC0415
    except ImportError:
        return "web"
    return "desktop"


def _spawn_self(*args: str) -> int:
    """Re-invoke the current Python process with the given args.

    Used so that `hello-agent start --mode web` becomes
    `hello-agent serve serve --no-open` (or similar) without us
    having to import the heavy web/desktop modules here.
    """
    cmd = [sys.executable, "-m", "hello_agent.cli.main", *args]
    logger.info("start: spawning {}", " ".join(cmd))
    # On Windows, CREATE_NEW_PROCESS_GROUP so the child can be signaled.
    kwargs: dict[str, Any] = {
        "stdin": None,
        "stdout": None,
        "stderr": None,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    # Replace this process with the child (cleaner than subprocess.run
    # + wait; the user wants `start` to "become" the chosen mode).
    try:
        os.execvp(cmd[0], cmd)  # noqa: S606
    except OSError as exc:
        typer_echo = typer.echo
        typer_echo(f"failed to exec {cmd}: {exc}", err=True)
        return 1
    return 0


@app.callback(invoke_without_command=True)
def start_main(
    ctx: typer.Context,
    mode: str = typer.Option(
        "auto",
        "--mode",
        "-m",
        help="Launch mode: auto / web / desktop / chat",
    ),
    list_mode: bool = typer.Option(
        False, "--list-modes", help="Print available modes and exit"
    ),
) -> None:
    """Launch the agent in the chosen mode (persisted across sessions)."""
    if list_mode:
        typer.echo("Available modes:")
        for m in VALID_MODES:
            typer.echo(f"  - {m}")
        typer.echo(
            "\nPersisted mode file: " + str(_mode_file())
        )
        return

    if mode not in VALID_MODES:
        typer.echo(
            f"invalid --mode {mode!r}; expected one of {VALID_MODES}",
            err=True,
        )
        raise typer.Exit(code=2)

    # Resolve `auto` and persist the chosen mode so the next `start`
    # remembers it.
    if mode == "auto":
        mode = _detect_mode()
    _write_mode(mode)
    logger.info("hello-agent start: mode={}", mode)

    # Dispatch.
    if mode == "web":
        # `serve serve` is the FastAPI + tray launcher. The user can
        # stop it with Ctrl+C (or tray Quit).
        _spawn_self("serve", "serve")
    elif mode == "desktop":
        # The desktop launcher opens a webview + spawns its own backend.
        _spawn_self("desktop")
    elif mode == "chat":
        _spawn_self("chat")
    else:  # pragma: no cover — guarded above
        typer.echo(f"unhandled mode {mode!r}", err=True)
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
