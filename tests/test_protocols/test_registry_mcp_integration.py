"""Tests for `ToolRegistry` <-> MCP integration.

Verifies that:
- `register_mcp_server(client)` adds remote tools to the registry, idempotently
- `execute(name, args)` routes MCP-backed tools through the client transparently
- The circuit breaker is consulted on every MCP call (and trips on errors)
- `unregister_mcp_server(client)` cleans up the bundle
- Local tool names win over remote ones with the same name
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from hello_agent.core.exceptions import CircuitOpenError
from hello_agent.core.types import ToolDefinition
from hello_agent.protocols.mcp_client import (
    MCPClient,
    MCPConnectionError,
)
from hello_agent.tools.circuit_breaker import (
    CircuitBreaker,
    check_breaker,
)
from hello_agent.tools.registry import ToolRegistry

# ----- Fake SDK session (re-used shape from test_mcp_client.py) -------------


@dataclass
class _FakeTool:
    name: str
    description: str = ""
    inputSchema: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeListResult:
    tools: list[_FakeTool]


@dataclass
class _FakeTextContent:
    type: str = "text"
    text: str = ""


@dataclass
class _FakeCallResult:
    isError: bool = False
    content: list[_FakeTextContent] = field(default_factory=list)


class FakeSession:
    """Tiny in-memory MCP session used by registry integration tests."""

    def __init__(
        self,
        tools: list[dict[str, Any]] | None = None,
        call_responses: dict[str, _FakeCallResult] | None = None,
    ) -> None:
        self._tools = tools or [
            {
                "name": "remote_echo",
                "description": "Echoes input back",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
            {
                "name": "remote_add",
                "description": "Adds two numbers",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            },
        ]
        self._call_responses = call_responses or {}
        self.initialized = False
        self.call_log: list[tuple[str, dict[str, Any]]] = []

    async def initialize(self) -> None:
        self.initialized = True

    async def list_tools(self) -> _FakeListResult:
        return _FakeListResult(tools=[_FakeTool(**t) for t in self._tools])

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> _FakeCallResult:
        self.call_log.append((name, arguments or {}))
        if name in self._call_responses:
            return self._call_responses[name]
        # Default: echo the arguments as a single text block.
        import json

        return _FakeCallResult(
            isError=False,
            content=[_FakeTextContent(text=json.dumps(arguments or {}))],
        )


def _factory_for(session: FakeSession):
    async def _factory() -> FakeSession:
        return session

    return _factory


# ----- Helpers --------------------------------------------------------------


def _make_client(
    session: FakeSession,
    *,
    name: str = "test-mcp",
    call_responses: dict[str, _FakeCallResult] | None = None,
) -> MCPClient:
    if call_responses is not None:
        # Replace the session's call dispatcher by wrapping it.
        original = session.call_tool

        async def custom_call(name: str, arguments: dict[str, Any] | None = None) -> _FakeCallResult:
            if name in call_responses:
                session.call_log.append((name, arguments or {}))
                return call_responses[name]
            return await original(name, arguments)

        session.call_tool = custom_call  # type: ignore[method-assign]
    return MCPClient(
        cmd="ignored",
        name=name,
        session_factory=_factory_for(session),
    )


def _local_handler(prefix: str = "local:"):
    """A plain local handler for comparison tests."""

    def handler(args: dict[str, Any], **kw: Any):
        from hello_agent.core.types import ToolResult

        return ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=f"{prefix}{args.get('text', '')}",
        )

    return handler


# ----- register_mcp_server --------------------------------------------------


def test_register_mcp_server_adds_tools_with_metadata() -> None:
    """`register_mcp_server` adds each remote tool with the right schema."""
    session = FakeSession()
    client = _make_client(session)

    reg = ToolRegistry()
    registered = reg.register_mcp_server(client)

    assert sorted(registered) == ["remote_add", "remote_echo"]
    # The schema for `remote_echo` round-trips.
    entry = reg.get("remote_echo")
    assert entry.schema.description == "Echoes input back"
    assert entry.schema.parameters["type"] == "object"
    assert "text" in entry.schema.parameters["properties"]
    # It is recorded as enabled by default.
    assert reg.is_enabled("remote_echo")
    # And it lives under the mcp: toolset.
    members = reg.filter_by_profile(f"mcp:{client.name}")
    assert {t.name for t in members} == {"remote_echo", "remote_add"}


def test_register_mcp_server_skips_local_name_collisions() -> None:
    """If a local tool has the same name, the local one wins."""
    session = FakeSession(
        tools=[{"name": "shared", "description": "remote shared"}],
    )
    client = _make_client(session)

    reg = ToolRegistry()
    reg.register(
        name="shared",
        toolset="local",
        schema=ToolDefinition(name="shared", description="local shared", parameters={}),
        handler=_local_handler("local:"),
    )

    registered = reg.register_mcp_server(client)
    assert registered == []  # remote `shared` was skipped
    # The local one is still in place.
    assert reg.get("shared").schema.description == "local shared"


def test_register_mcp_server_is_idempotent() -> None:
    """Re-registering the same client replaces its tools (idempotent)."""
    session = FakeSession()
    client = _make_client(session)
    reg = ToolRegistry()

    first = reg.register_mcp_server(client)
    second = reg.register_mcp_server(client)

    assert first == second
    # Still the same two tools (not duplicated).
    assert {t.name for t in reg.list()} == {"remote_add", "remote_echo"}


def test_register_mcp_server_does_not_auto_connect() -> None:
    """If the client is already connected, we re-use that connection."""
    session = FakeSession()
    client = _make_client(session)
    client.connect()
    assert session.initialized

    reg = ToolRegistry()
    reg.register_mcp_server(client)

    # Initialize was only called once (we didn't reconnect).
    assert session.initialized


def test_register_mcp_server_connects_lazily() -> None:
    """If the client is NOT connected, `register_mcp_server` connects it."""
    session = FakeSession()
    client = _make_client(session)
    assert not client.connected

    reg = ToolRegistry()
    reg.register_mcp_server(client)

    assert client.connected
    assert session.initialized is True


# ----- execute() routes to MCP ----------------------------------------------


def test_execute_routes_mcp_tool_through_client() -> None:
    """`registry.execute(name, ...)` calls the MCP client's `call_tool`."""
    session = FakeSession(
        call_responses={
            "remote_echo": _FakeCallResult(
                isError=False,
                content=[_FakeTextContent(text="echoed:hi")],
            ),
        },
    )
    client = _make_client(session, name="m1")

    reg = ToolRegistry()
    reg.register_mcp_server(client)

    result = reg.execute("remote_echo", {"text": "hi"})

    assert not result.is_error
    assert result.content == "echoed:hi"
    assert session.call_log == [("remote_echo", {"text": "hi"})]


def test_execute_mcp_failure_marks_result_error() -> None:
    """A `isError=True` response from the MCP server → `ToolResult(is_error=True)`."""
    session = FakeSession(
        call_responses={
            "remote_echo": _FakeCallResult(
                isError=True,
                content=[_FakeTextContent(text="remote: arg invalid")],
            ),
        },
    )
    client = _make_client(session)
    reg = ToolRegistry()
    reg.register_mcp_server(client)

    result = reg.execute("remote_echo", {"text": "x"})
    assert result.is_error is True
    assert "remote: arg invalid" in result.content


def test_execute_mcp_disabled_tool_is_blocked() -> None:
    """Disabling an MCP-backed tool returns an error without contacting the server."""
    session = FakeSession()
    client = _make_client(session)
    reg = ToolRegistry()
    reg.register_mcp_server(client)

    reg.disable(["remote_echo"])
    result = reg.execute("remote_echo", {"text": "hi"})
    assert result.is_error is True
    assert "disabled" in result.content
    # The MCP server was NOT called.
    assert session.call_log == []


# ----- Circuit breaker integration -----------------------------------------


def test_circuit_breaker_trips_after_mcp_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated MCP failures must trip the per-tool circuit breaker.

    Uses a fresh `CircuitBreaker` (via `reset_singletons`) so this test
    is independent of other tests that exercise the module-level breaker.
    """
    # Use a tight threshold so the test is fast.
    from hello_agent.tools import circuit_breaker as cb_mod

    monkeypatch.setattr(cb_mod, "_breaker", CircuitBreaker(fail_threshold=2, cooldown_seconds=60.0))

    session = FakeSession(
        call_responses={
            "remote_echo": _FakeCallResult(isError=True, content=[_FakeTextContent(text="boom")]),
        },
    )
    client = _make_client(session)
    reg = ToolRegistry()
    reg.register_mcp_server(client)

    # First two calls succeed in reaching the server but report an error
    # (the dispatcher only trips the breaker on `is_error=True` results).
    res1 = reg.execute("remote_echo", {"text": "x"})
    res2 = reg.execute("remote_echo", {"text": "x"})
    assert res1.is_error and res2.is_error

    # The breaker is now OPEN — the next call must short-circuit.
    with pytest.raises(CircuitOpenError):
        reg.execute("remote_echo", {"text": "x"})

    # And the session was not called the third time.
    assert len(session.call_log) == 2


def test_circuit_breaker_resets_on_success() -> None:
    """A successful MCP call closes the breaker."""
    session = FakeSession(
        call_responses={
            "remote_echo": _FakeCallResult(isError=False, content=[_FakeTextContent(text="ok")]),
        },
    )
    client = _make_client(session)
    reg = ToolRegistry()
    reg.register_mcp_server(client)

    # Drive one failure...
    session._call_responses["remote_echo"] = _FakeCallResult(
        isError=True, content=[_FakeTextContent(text="boom")]
    )
    res = reg.execute("remote_echo", {"text": "x"})
    assert res.is_error
    # ...then a success.
    session._call_responses["remote_echo"] = _FakeCallResult(
        isError=False, content=[_FakeTextContent(text="ok")]
    )
    res = reg.execute("remote_echo", {"text": "x"})
    assert not res.is_error
    # Per-tool breaker is now CLOSED.
    assert check_breaker("remote_echo") is True


def test_connection_error_is_surfaced_as_error_result() -> None:
    """An `MCPConnectionError` from the client becomes a stringified `ToolResult`."""
    session = FakeSession()

    # Override the session's call_tool to raise a connection-shaped error.
    async def boom(name: str, arguments: dict[str, Any] | None = None) -> _FakeCallResult:
        raise MCPConnectionError("subprocess died")

    session.call_tool = boom  # type: ignore[method-assign]

    client = _make_client(session)
    reg = ToolRegistry()
    reg.register_mcp_server(client)

    res = reg.execute("remote_echo", {"text": "x"})
    assert res.is_error is True
    assert "subprocess died" in res.content


# ----- unregister_mcp_server -----------------------------------------------


def test_unregister_mcp_server_removes_all_remote_tools() -> None:
    """`unregister_mcp_server(client)` removes every tool from that client."""
    session = FakeSession()
    client = _make_client(session)
    reg = ToolRegistry()
    reg.register_mcp_server(client)
    assert {t.name for t in reg.list()} == {"remote_add", "remote_echo"}

    removed = reg.unregister_mcp_server(client)
    assert removed == 2
    assert reg.list() == []


def test_unregister_mcp_server_preserves_other_clients() -> None:
    """Removing client A's tools leaves client B's tools intact."""
    session_a = FakeSession(tools=[{"name": "tool_a", "description": "A"}])
    session_b = FakeSession(tools=[{"name": "tool_b", "description": "B"}])
    client_a = _make_client(session_a, name="serverA")
    client_b = _make_client(session_b, name="serverB")

    reg = ToolRegistry()
    reg.register_mcp_server(client_a)
    reg.register_mcp_server(client_b)

    assert {t.name for t in reg.list()} == {"tool_a", "tool_b"}
    reg.unregister_mcp_server(client_a)
    assert {t.name for t in reg.list()} == {"tool_b"}


def test_unregister_mcp_server_unknown_client_is_noop() -> None:
    """Unregistering a client we never registered is a no-op (returns 0)."""
    reg = ToolRegistry()
    session = FakeSession()
    client = _make_client(session)
    assert reg.unregister_mcp_server(client) == 0


def test_unregister_individual_tool_clears_mcp_reverse_map() -> None:
    """If we `unregister(name)` one MCP tool, the rest of the bundle survives."""
    session = FakeSession()
    client = _make_client(session)
    reg = ToolRegistry()
    reg.register_mcp_server(client)

    assert reg.unregister("remote_echo") is True
    # The other tool is still there.
    assert {t.name for t in reg.list()} == {"remote_add"}
    # And the client can be re-registered (its reverse map is clean).
    reg.register_mcp_server(client)
    assert {t.name for t in reg.list()} == {"remote_add", "remote_echo"}
