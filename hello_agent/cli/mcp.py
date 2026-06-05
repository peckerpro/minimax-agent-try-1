"""`hello-agent mcp` 鈥?serve / connect to MCP servers."""
from __future__ import annotations

import asyncio
import shlex

import typer

from hello_agent.core.logging import get_logger

app = typer.Typer(help="MCP (Model Context Protocol) integration.")
logger = get_logger(__name__)


@app.command("serve")
def serve() -> None:
    """Run an MCP stdio server exposing all hello-agent tools."""
    from hello_agent.protocols.mcp_server import serve_stdio

    try:
        asyncio.run(serve_stdio())
    except KeyboardInterrupt:
        return


@app.command("connect")
def connect(
    command: str = typer.Argument(..., help="Command to spawn (e.g. `npx -y @modelcontextprotocol/server-filesystem .`)."),
    name: str | None = typer.Option(None, "--name", "-n", help="Display name for this connection."),
) -> None:
    """Connect to an external MCP server and merge its tools into our registry.

    v0.1 limitation: this is a *probe* 鈥?we spawn the server, list its tools,
    print them, and exit. v0.3 will keep the connection alive and route tool
    calls through it.
    """
    from hello_agent.protocols.mcp_client import probe_server

    try:
        tools = asyncio.run(probe_server(shlex.split(command), name=name or "external"))
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"connect failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Discovered {len(tools)} tools:")
    for t in tools:
        typer.echo(f"  - {t.get('name')}: {t.get('description', '')[:80]}")


if __name__ == "__main__":
    app()
