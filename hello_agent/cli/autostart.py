"""`hello-agent autostart` — Windows autostart helper CLI.

Subcommands:
    enable    Add hello-agent to HKCU\\...\\Run (current user, no admin needed)
    disable   Remove the entry (idempotent)
    status    Print whether the entry is present and what it points to
"""
from __future__ import annotations

import sys

import typer

from hello_agent.core.logging import get_logger
from hello_agent.windows.autostart import (
    AutostartUnsupportedError,
    get_autostart_entry,
)

app = typer.Typer(help="Manage Windows autostart (HKCU\\...\\Run\\hello-agent).")
logger = get_logger(__name__)


def _unsupported() -> None:
    """Print a Windows-only hint and exit non-zero."""
    typer.echo(
        f"autostart is Windows-only (HKCU\\...\\Run); current platform: {sys.platform}",
        err=True,
    )
    raise typer.Exit(code=1)


@app.command("enable")
def enable(
    repo_root: str | None = typer.Option(
        None, "--repo-root", help="Override the repo path written to the registry"
    ),
) -> None:
    """Enable hello-agent autostart on logon."""
    if sys.platform != "win32":
        _unsupported()
    from hello_agent.windows.autostart import enable_autostart

    ok = enable_autostart(repo_root=repo_root)
    if ok:
        typer.echo("autostart enabled.")
        raise typer.Exit(code=0)
    typer.echo("autostart enable FAILED; see logs.", err=True)
    raise typer.Exit(code=1)


@app.command("disable")
def disable() -> None:
    """Disable hello-agent autostart on logon."""
    if sys.platform != "win32":
        _unsupported()
    from hello_agent.windows.autostart import disable_autostart

    ok = disable_autostart()
    if ok:
        typer.echo("autostart disabled (or already absent).")
        raise typer.Exit(code=0)
    typer.echo("autostart disable FAILED; see logs.", err=True)
    raise typer.Exit(code=1)


@app.command("status")
def status() -> None:
    """Print whether autostart is enabled and what command it runs."""
    if sys.platform != "win32":
        _unsupported()
    from hello_agent.windows.autostart import is_autostart_enabled

    try:
        if not is_autostart_enabled():
            typer.echo("autostart: disabled (no registry entry).")
            raise typer.Exit(code=0)
    except AutostartUnsupportedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    entry = get_autostart_entry()
    if entry is None:
        typer.echo("autostart: enabled (but could not read command).")
        raise typer.Exit(code=0)
    typer.echo("autostart: enabled")
    typer.echo(f"  name:    {entry.name}")
    typer.echo(f"  command: {entry.command}")


if __name__ == "__main__":
    app()