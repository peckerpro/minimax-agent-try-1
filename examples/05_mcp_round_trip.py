"""Example 05 — MCP round-trip: spawn hello-agent as an MCP server, connect from another MCPClient.

`hello_agent.protocols.mcp_server.serve_stdio` exposes all builtin tools
as a JSON-RPC stdio MCP server. `hello_agent.protocols.mcp_client.MCPClient`
speaks the same protocol. This example spawns the server as a subprocess
(`python -m hello_agent.cli.mcp serve`), connects from a fresh `MCPClient`,
calls one tool through the wire, and asserts the result round-trips.

Real usage:

    uv run python examples/05_mcp_round_trip.py

Self-test (no extra setup — uses `python -m hello_agent.cli.mcp serve`):

    uv run python examples/05_mcp_round_trip.py --self-test

In self-test mode we connect, list tools, call `read_file` against this
very example file, then disconnect cleanly. No LLM calls happen.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Server command: spawn hello-agent's MCP stdio server as a subprocess.
# `python -m hello_agent.cli.mcp serve` is the same entry point the
# `hello-agent mcp serve` CLI uses internally.
_SERVER_CMD: list[str] = [sys.executable, "-m", "hello_agent.cli.mcp", "serve"]


def _spawn_server_and_round_trip() -> tuple[int, list[str]]:
    """Spawn the MCP server, connect, list tools, call read_file, disconnect.

    Returns (exit_status, list_of_remote_tool_names).
    """
    from hello_agent.protocols.mcp_client import MCPClient

    client = MCPClient(
        cmd=_SERVER_CMD,
        cwd=str(_REPO_ROOT),
        env={**os.environ, "HELLO_AGENT_PROFILE": "test", "HELLO_AGENT_HOME": str(_REPO_ROOT / ".harness" / "test_home")},
        name="hello-agent-server",
        read_timeout_seconds=10.0,
    )

    try:
        names = client.connect()
        listed = client.list_tools()
        listed_names = sorted(str(t["name"]) for t in listed)
        # Round-trip a tool call. We ask the server to read its own source file.
        # read_file is a builtin; if it's been disabled this will fail loudly.
        target = str((_REPO_ROOT / "hello_agent" / "__init__.py").resolve())
        result = client.call_tool("read_file", {"path": target, "max_bytes": 200})
        if result.is_error:
            print(f"call_tool read_file returned is_error=True: {result.text!r}", file=sys.stderr)
            return 1, listed_names
        if "hello-agent" not in result.text and "__version__" not in result.text:
            print(f"unexpected read_file payload: {result.text[:200]!r}", file=sys.stderr)
            return 1, listed_names
        return 0, listed_names
    finally:
        client.close()


def _run_self_test() -> int:
    """Offline smoke — spawns the MCP server, does one round-trip, exits."""
    # Give the subprocess a moment; on slow CI hosts the stdio handshake
    # can race the first list_tools call.
    start = time.time()
    rc, names = _spawn_server_and_round_trip()
    elapsed = time.time() - start
    if rc != 0:
        return rc
    assert names, "MCP server advertised zero tools"
    assert "read_file" in names, f"read_file missing from advertised tools: {names}"
    print(
        f"[self-test] OK: MCP round-trip succeeded in {elapsed:.2f}s; "
        f"server advertised {len(names)} tools (sample: {names[:5]}…)"
    )
    return 0


def _run_live() -> int:
    """Same as self-test but with a more verbose printout so the user sees the wire."""
    rc, names = _spawn_server_and_round_trip()
    print(f"Discovered {len(names)} tools via MCP:")
    for n in names:
        print(f"  - {n}")
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spawn hello-agent as MCP server and round-trip a tool call.")
    parser.add_argument("--self-test", action="store_true", help="Offline smoke; no extra setup")
    args = parser.parse_args(argv)
    try:
        return _run_self_test() if args.self_test else _run_live()
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())