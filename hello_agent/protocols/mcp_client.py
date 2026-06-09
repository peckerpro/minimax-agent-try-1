"""MCP (Model Context Protocol) client.

Spawns an MCP server as a subprocess, performs the JSON-RPC handshake
(`initialize` + `notifications/initialized`), and exposes the remote tools
through a small sync-ish API:

    >>> client = MCPClient(["npx", "-y", "@modelcontextprotocol/server-filesystem", "."])
    >>> client.connect()                  # handshake, returns list of remote tool names
    >>> client.list_tools()               # [{name, description, inputSchema}, ...]
    >>> resp = client.call_tool("read_file", {"path": "/tmp/x.txt"})
    >>> client.close()                    # clean shutdown

Transport: stdio only (v0.1 + v0.2). SSE / HTTP transports are deferred to v0.3+.

Lifecycle:
    1. `__init__(cmd, args, cwd=None, env=None)` — store config, DO NOT spawn yet.
    2. `connect()` — spawn subprocess, run `initialize`, send `initialized` notif.
    3. `list_tools()` — call `tools/list`, cache + return.
    4. `call_tool(name, args)` — call `tools/call`, return `ToolResponse`-shaped dict.
    5. `close()` — tear down the stdio streams + terminate subprocess (idempotent).

The `mcp` SDK is lazy-imported at first use so the rest of hello-agent
stays importable in environments where `mcp` is not installed.

Threading: `MCPClient` is NOT thread-safe — it owns one stdio subprocess and
serialises requests through the underlying SDK session. For concurrent
MCP traffic, spawn multiple clients.

This module also exposes `probe_server(cmd, name)` — a one-shot async helper
that connects, lists tools, and disconnects. The CLI's `mcp connect` subcommand
uses it for "discover and exit" behavior; the long-lived registry uses
`MCPClient` directly.
"""
from __future__ import annotations

import asyncio
import os
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from hello_agent.core.exceptions import HelloAgentError, ToolError
from hello_agent.core.logging import get_logger

_logger = get_logger(__name__)


# ----- Errors ---------------------------------------------------------------


class MCPError(HelloAgentError):
    """Base error for MCP client / server failures."""


class MCPConnectionError(MCPError):
    """Could not spawn / handshake the MCP subprocess."""


class MCPCallError(ToolError):
    """The remote `tools/call` returned a non-zero result or an error.

    Inherits from `ToolError` so circuit-breaker / registry error routing
    can treat it like a local tool failure.
    """


# ----- Public types ---------------------------------------------------------


@dataclass
class MCPToolInfo:
    """Lightweight description of a remote tool (the result of `tools/list`)."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


@dataclass
class MCPCallResult:
    """Result of a single `tools/call` invocation, normalized to text content.

    Mirrors the JSON-RPC `CallToolResult` shape but flattens content to a
    single text string so registry / circuit-breaker code can treat it like
    a local tool's stdout.
    """

    text: str
    is_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "is_error": self.is_error}


# ----- Client ---------------------------------------------------------------


class MCPClient:
    """Long-lived stdio MCP client.

    Construct with the command to spawn (`cmd` is the executable, `args` is
    the full argv). The subprocess is not started until `connect()` is called
    (or the object is used as a context manager — `with MCPClient(...) as c:`).
    """

    def __init__(
        self,
        cmd: str | list[str],
        args: list[str] | None = None,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: dict[str, str] | None = None,
        name: str = "external",
        read_timeout_seconds: float = 30.0,
        # Test-only hooks — when set, the client skips the real
        # `mcp.client.stdio.stdio_client` + `ClientSession` machinery and
        # uses the injected factory instead. `session_factory` is an async
        # callable that, when awaited, returns an object with the
        # `initialize()`, `list_tools()`, and `call_tool(name, arguments=)`
        # methods of `mcp.client.session.ClientSession`. Production callers
        # leave this as None.
        session_factory: Any = None,
    ) -> None:
        # Normalize to a (command, args) pair so callers can pass either
        # MCPClient("npx", ["-y", "..."]) or MCPClient(["npx", "-y", "..."]).
        if isinstance(cmd, (list, tuple)):
            if not cmd:
                raise MCPConnectionError("MCPClient: empty command list")
            if args is not None:
                raise MCPConnectionError(
                    "MCPClient: pass either a list command OR (cmd, args), not both"
                )
            self._command = str(cmd[0])
            self._args: list[str] = [str(a) for a in cmd[1:]]
        else:
            self._command = str(cmd)
            self._args = list(args) if args else []

        self._cwd = os.fspath(cwd) if cwd is not None else None
        self._env = env
        self.name = name
        self._read_timeout_seconds = read_timeout_seconds
        self._session_factory = session_factory

        # Async state — populated by `connect()`, cleared by `close()`.
        self._stack: AsyncExitStack | None = None
        self._session: Any = None  # mcp.client.session.ClientSession (or test fake)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tools: list[MCPToolInfo] = []
        self._connected = False
        # Serialize all in-flight operations on the underlying session.
        # The MCP SDK is async, but we expose sync methods; the lock keeps
        # connect/list/call/close from interleaving across threads.
        self._lock = threading.RLock()

    # ---- properties ----

    @property
    def connected(self) -> bool:
        return self._connected and self._session is not None

    @property
    def tools(self) -> list[MCPToolInfo]:
        """Cached tool list (populated by `connect()` / `list_tools()`)."""
        return list(self._tools)

    # ---- public API ----

    def connect(self) -> list[str]:
        """Spawn the subprocess, run the MCP handshake, and cache the tool list.

        Returns the list of remote tool names (strings) on success. Raises
        `MCPConnectionError` on spawn / handshake failure.

        Safe to call multiple times — re-connecting after `close()` is allowed.
        """
        with self._lock:
            if self._connected:
                return [t.name for t in self._tools]
            self._ensure_loop()
            try:
                future = asyncio.run_coroutine_threadsafe(self._aconnect(), self._loop)
                tools = future.result()
            except Exception as exc:  # noqa: BLE001
                # Best-effort teardown so a failed handshake leaves no dangling
                # streams or subprocesses.
                self._teardown_locked()
                raise MCPConnectionError(
                    f"MCP handshake with {self.name!r} ({self._command}) failed: {exc}"
                ) from exc
            self._connected = True
            return tools

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the remote tool list as a list of dicts.

        Each dict has the shape `{"name", "description", "inputSchema"}` —
        the same shape the `hello_agent.tools.registry.ToolRegistry` stores
        in `ToolDefinition.parameters`.
        """
        with self._lock:
            self._require_connected()
            # `list_tools` is idempotent on the server side and we cache the
            # result. If the caller wants a fresh list, they can `close()` +
            # `connect()` again.
            return [t.to_dict() for t in self._tools]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> MCPCallResult:
        """Invoke a remote tool by name. Returns `MCPCallResult`.

        `is_error=True` if the remote server reported a tool-level error
        (the call itself succeeded; the tool's logic returned a failure).
        Connection-level failures raise `MCPConnectionError`; tool-level
        failures are surfaced via `is_error` so the caller can decide
        whether to trip the circuit breaker.
        """
        with self._lock:
            self._require_connected()
            assert self._session is not None  # for type checkers
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._acall_tool(name, arguments or {}), self._loop
                )
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                raise MCPConnectionError(
                    f"MCP call_tool({name}) on {self.name!r} failed: {exc}"
                ) from exc
        return result

    def close(self) -> None:
        """Tear down the stdio session and terminate the subprocess.

        Idempotent — safe to call from `__exit__`, error paths, and shutdown
        hooks. Never raises.
        """
        with self._lock:
            self._teardown_locked()

    # ---- context manager ----

    def __enter__(self) -> MCPClient:
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def __del__(self) -> None:  # noqa: D401 — best-effort cleanup
        try:
            self.close()
        except Exception:  # noqa: BLE001, S110 — destructor must never raise
            pass

    # ---- async helpers (run on the dedicated event loop) ----

    async def _aconnect(self) -> list[str]:
        # Test path: injected session factory bypasses the real SDK.
        if self._session_factory is not None:
            self._session = await self._session_factory()
            await self._session.initialize()
            listed = await self._session.list_tools()
            self._tools = [
                MCPToolInfo(
                    name=t.name,
                    description=t.description or "",
                    input_schema=dict(t.inputSchema or {}),
                )
                for t in listed.tools
            ]
            return [t.name for t in self._tools]

        # Production path: lazy import — keep `mcp` SDK optional at module import time.
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=self._env,
            cwd=self._cwd,
        )
        self._stack = AsyncExitStack()
        # `stdio_client` is a context manager that yields (read_stream, write_stream)
        # and is responsible for spawning + reaping the subprocess.
        stdio_cm = stdio_client(params)
        read_stream, write_stream = await self._stack.enter_async_context(stdio_cm)
        self._session = ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=self._read_timeout_seconds),
        )
        await self._stack.enter_async_context(self._session)
        # MCP `initialize` handshake + `notifications/initialized` are both
        # handled by `session.initialize()` in the 1.x SDK.
        await self._session.initialize()

        listed = await self._session.list_tools()
        self._tools = [
            MCPToolInfo(
                name=t.name,
                description=t.description or "",
                input_schema=dict(t.inputSchema or {}),
            )
            for t in listed.tools
        ]
        return [t.name for t in self._tools]

    async def _acall_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        # The SDK's CallToolResult has `.content: list[Content]` and `.isError`.
        result = await self._session.call_tool(name, arguments=arguments)
        is_error = bool(getattr(result, "isError", False))
        text_parts: list[str] = []
        for block in getattr(result, "content", []) or []:
            # `mcp.types.TextContent` is the common case; ignore images etc.
            text = getattr(block, "text", None)
            if text is not None:
                text_parts.append(str(text))
        return MCPCallResult(text="\n".join(text_parts), is_error=is_error)

    def _ensure_loop(self) -> None:
        """Make sure we have an event loop to run async ops on.

        A MCPClient is long-lived, so we keep a dedicated background loop
        running on a daemon thread for the lifetime of the connection.
        """
        if self._loop is not None and self._loop.is_running():
            return

        ready = threading.Event()
        loop_holder: dict[str, Any] = {}

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop_holder["loop"] = loop
            ready.set()
            try:
                loop.run_forever()
            finally:
                loop.close()

        thread = threading.Thread(target=_runner, name=f"mcp-client-{self.name}", daemon=True)
        thread.start()
        ready.wait(timeout=5.0)
        if "loop" not in loop_holder:
            raise MCPConnectionError("MCPClient: failed to start event loop")
        self._loop = loop_holder["loop"]

    def _teardown_locked(self) -> None:
        """Tear down the connection. Caller holds `self._lock`."""
        if self._stack is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(self._stack.aclose(), self._loop)
                future.result(timeout=5.0)
            except Exception as exc:  # noqa: BLE001
                _logger.debug("MCPClient %s: AsyncExitStack teardown raised: %s", self.name, exc)
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:  # noqa: BLE001, S110
                pass
        self._stack = None
        self._session = None
        self._loop = None
        self._tools = []
        self._connected = False

    def _require_connected(self) -> None:
        if not self._connected or self._session is None:
            raise MCPConnectionError(
                f"MCPClient {self.name!r} is not connected — call connect() first"
            )

    # ---- repr ----

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        state = "connected" if self._connected else "idle"
        return f"MCPClient(name={self.name!r}, command={self._command!r}, args={self._args!r}, state={state})"


# ----- Module-level helpers -------------------------------------------------


async def probe_server(
    cmd: list[str],
    *,
    name: str = "external",
    cwd: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
    read_timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    """One-shot helper: connect, list tools, disconnect. Used by `mcp connect`.

    Returns a list of `{"name", "description", "inputSchema"}` dicts.
    """
    client = MCPClient(
        cmd=cmd,
        cwd=cwd,
        env=env,
        name=name,
        read_timeout_seconds=read_timeout_seconds,
    )
    try:
        client.connect()
        return client.list_tools()
    finally:
        client.close()


__all__ = [
    "MCPClient",
    "MCPToolInfo",
    "MCPCallResult",
    "MCPError",
    "MCPConnectionError",
    "MCPCallError",
    "probe_server",
]
