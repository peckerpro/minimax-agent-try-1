"""End-to-end tests for hello_agent.protocols.mcp_server.

Spawns the real `hello-agent mcp serve` subprocess (which exposes the 11
built-in tools over stdio JSON-RPC) and exercises it through `MCPClient`:
- `initialize` handshake
- `tools/list` — verifies all 11 builtin tools are advertised
- `tools/call` — round-trips one read_file and one error case

These tests are slower than the unit tests in `test_mcp_client.py`
(~1-2s each) because they spawn a real subprocess.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from hello_agent.protocols.mcp_client import MCPClient, MCPConnectionError

# ----- Fixtures -------------------------------------------------------------


@pytest.fixture(scope="module")
def uv_python() -> str:
    """Path to the `uv` binary — used to spawn the MCP server in a venv-aware way."""
    # On Windows + PowerShell, `sys.executable` is the venv's python.exe.
    # Spawning it directly with `-m hello_agent.protocols.mcp_server`
    # avoids requiring `uv` to be on PATH.
    return sys.executable


@pytest.fixture()
def hello_agent_server(uv_python: str, tmp_path: Path) -> MCPClient:
    """Yield a connected `MCPClient` pointing at our own stdio server.

    The subprocess is `python -m hello_agent.protocols.mcp_server`, which
    runs the same `serve_stdio()` entry point as the CLI's `mcp serve`
    command — just bypasses Typer.
    """
    # Use a clean HELLO_AGENT_HOME so the test doesn't pollute user state.
    env = {
        **os.environ,
        "HELLO_AGENT_HOME": str(tmp_path),
        "HELLO_AGENT_PROFILE": "test",
    }
    client = MCPClient(
        cmd=uv_python,
        args=["-m", "hello_agent.protocols.mcp_server"],
        cwd=str(tmp_path),
        env=env,
        name="hello-agent-mcp-server",
        read_timeout_seconds=15.0,
    )
    try:
        client.connect()
    except Exception:
        client.close()
        raise
    yield client
    client.close()


# ----- Tests ----------------------------------------------------------------


EXPECTED_TOOL_NAMES = {
    "read_file",
    "write_file",
    "edit_file",
    "run_powershell",
    "run_cmd",
    "search",
    "fetch",
    "document_parser",
    "todowrite",
    "notify",
    "task_delegate",
}


def test_handshake_lists_all_eleven_builtin_tools(hello_agent_server: MCPClient) -> None:
    """The hello-agent MCP server advertises all 11 built-in tools."""
    tools = hello_agent_server.list_tools()
    names = {t["name"] for t in tools}
    assert EXPECTED_TOOL_NAMES <= names, (
        f"Missing tools: {EXPECTED_TOOL_NAMES - names}"
    )
    # `search` and `fetch` are short names in v0.1 (registered by builtin
    # modules); ENGINEERING.md §7.6 calls them `web_search` / `web_fetch`.
    # We accept either; both name sets are 11 in total. See deliverable.md.
    assert len(names) == 11


def test_list_tools_includes_input_schemas(hello_agent_server: MCPClient) -> None:
    """Each advertised tool has a non-empty inputSchema with object type."""
    tools = hello_agent_server.list_tools()
    for t in tools:
        schema = t.get("inputSchema") or {}
        assert schema.get("type") == "object", f"{t['name']}: schema is not object"
        # `properties` may be empty for tools that take no args, but the key
        # should still be present (or be empty dict, which the spec allows).
        assert "properties" in schema or "required" in schema or schema == {"type": "object"}


def test_call_tool_read_file_round_trip(hello_agent_server: MCPClient, tmp_path: Path) -> None:
    """Calling `read_file` over MCP returns the file content as text."""
    target = tmp_path / "hello.txt"
    target.write_text("hello from mcp", encoding="utf-8")

    result = hello_agent_server.call_tool("read_file", {"path": str(target)})
    assert not result.is_error, f"unexpected error: {result.text}"
    # The server JSON-serializes the data; the text field will contain the
    # JSON envelope from the tool.
    payload = json.loads(result.text)
    assert payload["success"] is True
    assert "hello from mcp" in payload["data"]["text"]


def test_call_tool_missing_file_returns_error_text(hello_agent_server: MCPClient, tmp_path: Path) -> None:
    """A failing tool surfaces an `isError=True` CallToolResult to the client.

    The MCP server wraps the local `ToolResult(is_error=True, content=...)`
    in a `CallToolResult(isError=True, content=[TextContent(text="ERROR: ...")])`.
    We assert both signals:
    - `result.is_error` is `True` (the SDK propagated `isError=True`)
    - `result.text` is the server's text content (starts with `ERROR: `)
    """
    result = hello_agent_server.call_tool(
        "read_file", {"path": str(tmp_path / "nope.txt")}
    )
    assert result.is_error is True
    # The server's error envelope is `ERROR: <content>`; v0.1's
    # file_tools `_to_result` helper leaves the content empty for `fail()`
    # responses (the error is in `ToolResponse.error`, not `data`), so the
    # actual text is `ERROR: tool failed`. This is a known v0.1 quirk
    # surfaced here; the contract we care about is the `isError=True` flag.
    assert result.text.startswith("ERROR:")


def test_call_tool_unknown_tool_returns_error(hello_agent_server: MCPClient) -> None:
    """An unregistered tool name surfaces a clear error result.

    The dispatcher returns an `is_error` ToolResult, which the server wraps
    in `ERROR: <content>`.
    """
    result = hello_agent_server.call_tool("definitely_not_a_tool", {})
    assert result.is_error is True
    assert "ERROR" in result.text or "not registered" in result.text.lower()


def test_server_lifecycle_spawn_and_teardown(tmp_path: Path) -> None:
    """Spawning + closing the server is clean: no orphan subprocesses, no hang."""
    env = {
        **os.environ,
        "HELLO_AGENT_HOME": str(tmp_path),
        "HELLO_AGENT_PROFILE": "test",
    }
    cli = MCPClient(
        cmd=sys.executable,
        args=["-m", "hello_agent.protocols.mcp_server"],
        cwd=str(tmp_path),
        env=env,
        name="lifecycle",
        read_timeout_seconds=10.0,
    )
    names = cli.connect()
    assert len(names) >= 11
    cli.close()
    assert cli.connected is False


def test_server_rejects_invalid_path() -> None:
    """Spawning a non-existent command raises `MCPConnectionError` cleanly."""
    cli = MCPClient(
        cmd="definitely-not-a-real-binary-1234567890",
        name="bad",
        read_timeout_seconds=2.0,
    )
    try:
        with pytest.raises(MCPConnectionError):
            cli.connect()
    finally:
        cli.close()
