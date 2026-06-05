"""`hello-agent` typer CLI.

Top-level subcommands:
- chat     interactive TUI
- run      one-shot query
- tools    list / enable / disable / show
- rag      index / query
- memory   show / search / export / forget
- mcp      serve / connect
- serve    start web UI + tray
- doctor   env self-check
- completion  shell completion script
- autostart  enable / disable Windows autostart
"""
import os

import typer

from hello_agent import __version__
from hello_agent.core.logging import setup_logging
from hello_agent.core.paths import (
    _apply_profile_override,
    ensure_home,
)

app = typer.Typer(
    name="hello-agent",
    help="Personal Windows Python agent — Hermes-inspired.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
    invoke_without_command=True,
)


def _register_subcommands() -> None:
    """Register all subcommand typer apps.

    `chat` is registered as a top-level COMMAND (not via add_typer) so that
    `hello-agent chat "ping"` is parsed as `chat` + positional message,
    not as `chat` + subcommand `ping`.

    Other subcommands use add_typer because they have multiple sub-subcommands.
    """
    from hello_agent.cli import (  # noqa: PLC0415 — lazy import
        chat_app,
        completions,
        doctor,
        mcp,
        memory,
        rag,
        run,
        serve,
        tools_cmd,
    )

    # chat is a Typer app whose @app.callback handles the message arg.
    # We add it via add_typer so typer exposes it under the "chat" subcommand
    # name, but the callback (no subcommands) takes the message directly.
    app.add_typer(chat_app.app, name="chat")
    app.add_typer(run.app, name="run")
    app.add_typer(serve.app, name="serve")
    app.add_typer(rag.app, name="rag")
    app.add_typer(memory.app, name="memory")
    app.add_typer(tools_cmd.app, name="tools")
    app.add_typer(mcp.app, name="mcp")
    app.add_typer(doctor.app, name="doctor")
    app.add_typer(completions.app, name="completion")


# Subcommands MUST be registered at module-import time so typer can dispatch
# `hello-agent chat ...`, `hello-agent run ...`, etc. Registering inside the
# callback is too late — typer resolves the subcommand BEFORE running the
# callback. The cost is unavoidable for a typer-based multi-subcommand CLI.
_register_subcommands()


@app.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Use a named profile"),
    log_level: str | None = typer.Option(None, "--log-level", help="Override LOG_LEVEL"),
) -> None:
    """hello-agent — Personal Windows Python agent."""
    if profile:
        os.environ["HELLO_AGENT_PROFILE"] = profile
    _apply_profile_override()
    ensure_home()
    setup_logging(level=log_level)

    if version:
        typer.echo(f"hello-agent {__version__}")
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
