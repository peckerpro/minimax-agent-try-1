"""MCP (Model Context Protocol) stdio server.

Exposes all 11 built-in hello-agent tools (`read_file`, `write_file`,
`edit_file`, `run_powershell`, `run_cmd`, `web_search`, `web_fetch`,
`document_parser`, `todowrite`, `notify`, `task_delegate`) to any MCP
client that speaks the JSON-RPC stdio protocol.

Usage:
    # As a Python entry point
    from hello_agent.protocols.mcp_server import serve_stdio
    asyncio.run(serve_stdio())

    # Via the CLI (preferred for humans)
    uv run hello-agent mcp serve

The server is intentionally thin: it builds a `ToolRegistry` with the
full builtin set, then translates MCP `tools/list` and `tools/call`
JSON-RPC methods into `registry.list_tool_definitions()` and
`registry.execute(name, args, session_id="mcp")`.

Tool result mapping:
- On `success=True`:
    Returns `TextContent(text=json.dumps(result.data, ensure_ascii=False, indent=2))`
- On `success=False`:
    Returns `TextContent(text=f"ERROR: {result.error}\\n{result.hint or ''}")`

The `mcp` SDK is lazy-imported so the rest of hello-agent stays importable
in environments where the `mcp` extra is not installed.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from hello_agent.core.logging import get_logger
from hello_agent.core.types import ToolDefinition
from hello_agent.tools.registry import ToolRegistry

_logger = get_logger(__name__)


def build_registry(*, auto_discover: bool = True) -> ToolRegistry:
    """Construct a `ToolRegistry` populated with all 11 builtin tools.

    Defaults to `auto_discover=True` so callers (server, examples, tests)
    don't have to remember to opt in. Pass `auto_discover=False` if you
    need a bare registry for a different toolset.
    """
    return ToolRegistry(auto_discover=auto_discover)


# ----- Server factory --------------------------------------------------------


def make_server(registry: ToolRegistry | None = None, *, server_name: str = "hello-agent") -> Any:
    """Build a configured `mcp.server.Server` instance.

    The returned server has two handlers wired up:
    - `list_tools()`  — returns the full builtin tool list (all, not enabled-only,
                       because the MCP client is in control of what to call).
    - `call_tool(name, arguments)` — routes through `registry.execute()` and
                       serializes the result. Errors are returned with
                       `isError=True` on the `CallToolResult` so the MCP
                       client can distinguish tool failures from successful
                       returns; success results carry the same payload
                       (text or JSON-serialized data) in `content[0].text`.
    """
    # Lazy imports — keep the `mcp` SDK optional at module import time.
    from mcp.server import Server
    from mcp.types import CallToolResult, TextContent, Tool

    if registry is None:
        registry = build_registry()

    server: Any = Server(server_name)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        out: list[Tool] = []
        for entry in registry.list_all():
            schema: ToolDefinition = entry.schema
            # `inputSchema` must be a JSON Schema object — `registry` stores
            # exactly that, so pass through.
            out.append(
                Tool(
                    name=schema.name,
                    description=schema.description or "",
                    inputSchema=dict(schema.parameters or {}),
                )
            )
        return out

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        result = registry.execute(name, arguments or {}, session_id="mcp")
        if result.is_error:
            # `ToolResult.content` is a stringified JSON error; surface it
            # as `isError=True` so the client distinguishes failure from
            # success. The leading `ERROR: ` prefix is a courtesy for
            # humans tailing the server logs.
            err_text = result.content or "tool failed"
            return CallToolResult(
                content=[TextContent(type="text", text=f"ERROR: {err_text}")],
                isError=True,
            )
        # Success — serialize the data. If the tool returned a string,
        # pass it through without re-encoding to keep call/result
        # round-trips readable.
        if isinstance(result.content, str):
            payload = result.content
        else:
            payload = json.dumps(
                _safe_json(result.content),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        return CallToolResult(
            content=[TextContent(type="text", text=payload)],
            isError=False,
        )

    return server


# ----- Entry points ---------------------------------------------------------


async def serve_stdio(registry: ToolRegistry | None = None) -> None:
    """Run the MCP stdio server. Blocks until stdin closes / KeyboardInterrupt."""
    from mcp.server.stdio import stdio_server

    server = make_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Synchronous entry point — used by the `mcp serve` CLI subcommand."""
    try:
        asyncio.run(serve_stdio())
    except KeyboardInterrupt:
        # Normal shutdown (Ctrl+C in the host shell).
        return


# ----- Helpers ---------------------------------------------------------------


def _safe_json(value: Any) -> Any:
    """Best-effort JSON-safe coercion for tool data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(v) for v in value]
    return str(value)


__all__ = [
    "build_registry",
    "make_server",
    "serve_stdio",
    "main",
]


if __name__ == "__main__":
    main()
