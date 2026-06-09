"""MCP (Model Context Protocol) adapters — client + server.

This package exposes two pieces:

- `mcp_client` — `MCPClient` and `probe_server`. Spawn an external MCP server,
  handshake, list/call remote tools. Used by `ToolRegistry` for "remote tool
  routing" and by the `hello-agent mcp connect` CLI subcommand for "discover
  and exit" probes.
- `mcp_server` — `serve_stdio` / `build_registry` / `make_server`. Expose all
  11 built-in hello-agent tools as a JSON-RPC stdio MCP server. Used by
  `hello-agent mcp serve`.

Both modules lazy-import the `mcp` SDK so the rest of hello-agent stays
importable in environments where the `mcp` extra is not installed.
"""
from __future__ import annotations

from hello_agent.protocols import mcp_client, mcp_server

__all__ = ["mcp_client", "mcp_server"]
