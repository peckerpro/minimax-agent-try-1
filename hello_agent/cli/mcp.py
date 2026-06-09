"""`hello-agent mcp` — serve / connect to MCP servers."""
from __future__ import annotations

import asyncio
import shlex

import typer

from hello_agent.core.logging import get_logger

app = typer.Typer(help="MCP (Model Context Protocol) integration.")
logger = get_logger(__name__)


@app.command("serve")
def serve() -> None:
    """Run an MCP stdio server exposing all hello-agent tools.

    The server speaks JSON-RPC 2.0 over stdio and registers the 11 built-in
    tools (read_file / write_file / edit_file / run_powershell / run_cmd /
    search / fetch / document_parser / todowrite / notify / task_delegate).
    Connect it from Claude Desktop, mcp-inspector, or any MCP-compatible
    client.
    """
    from hello_agent.protocols.mcp_server import serve_stdio

    try:
        asyncio.run(serve_stdio())
    except KeyboardInterrupt:
        return


@app.command("connect")
def connect(
    command: str = typer.Argument(
        ...,
        help=(
            "Command to spawn (e.g. `npx -y @modelcontextprotocol/server-filesystem .`). "
            "Quote it; we split with shlex."
        ),
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Display name for this connection."),
    register: bool = typer.Option(
        False,
        "--register",
        "-r",
        help="Merge the discovered tools into the shared hello-agent registry (in-process).",
    ),
) -> None:
    """Connect to an external MCP server and (optionally) register its tools.

    v0.1 / v0.2 default behavior (no `--register`): spawn the server, list
    its tools, print them, and exit. This is the "discover and exit" probe.

    With `--register`: the connection stays alive and the remote tools are
    merged into the shared `hello_agent.tools.registry.registry`, so the
    ReAct agent can call them by name like any local tool.
    """
    from hello_agent.protocols.mcp_client import MCPClient

    args_list = shlex.split(command)
    if not args_list:
        typer.echo("connect: empty command", err=True)
        raise typer.Exit(code=2)

    server_name = name or "external"
    client = MCPClient(cmd=args_list, name=server_name)
    try:
        tools = _probe_and_maybe_register(client, server_name, register)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"connect failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Discovered {len(tools)} tools:")
    for t in tools:
        desc = str(t.get("description", ""))[:80]
        typer.echo(f"  - {t.get('name')}: {desc}")


def _probe_and_maybe_register(client, server_name: str, should_register: bool):
    """Shared body for `connect`. Returns the tool list (dicts)."""
    from hello_agent.tools.registry import registry

    # First, probe: connect, list, disconnect (idempotent for re-probes).
    # We always start with a fresh probe so the printed list matches what
    # the server really advertises.
    cmd_argv = [client._command, *client._args]
    listed = probe_server_sync(cmd_argv, name=server_name)
    if should_register:
        # Re-connect and keep the connection alive for the registry.
        client.connect()
        registry.register_mcp_server(client)
    return listed


def probe_server_sync(cmd_argv: list[str], *, name: str) -> list[dict[str, object]]:
    """Sync wrapper around the async `probe_server` for CLI use."""
    from hello_agent.protocols.mcp_client import probe_server

    return asyncio.run(probe_server(cmd_argv, name=name))


if __name__ == "__main__":
    app()
