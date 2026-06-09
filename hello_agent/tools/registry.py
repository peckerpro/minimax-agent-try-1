"""Tool auto-discovery + dispatch.

Borrowed from `NousResearch/hermes-agent/tools/registry.py` with:
- Added `dangerous` flag for confirmation-gated tools
- Added per-session confirmation cache
- Added `unregister()`, `list()` (alias for `list_all()`), and
  `filter_by_profile()` for dynamic per-agent toolset shaping.
- Added `auto_discover` opt-in to `__init__` so a freshly-built
  `ToolRegistry` can populate itself with builtin tools in one line.
- Added `register_mcp_server(client)` and `unregister_mcp_server(name)`
  to merge remote MCP tools into the registry; `execute()` routes to the
  remote client transparently and the per-tool circuit breaker still
  applies (v0.2 Day 6).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hello_agent.core.exceptions import CircuitOpenError, ToolNotFoundError
from hello_agent.core.types import ToolDefinition, ToolResult
from hello_agent.tools.circuit_breaker import (
    check_breaker,
    record_failure,
    record_success,
)

_logger = logging.getLogger(__name__)


@dataclass
class _RegisteredTool:
    name: str
    toolset: str
    schema: ToolDefinition
    handler: Callable[..., ToolResult]
    check_fn: Callable[[], bool] | None = None
    requires_env: list[str] = field(default_factory=list)
    dangerous: bool = False
    # v0.2 Day 6: if `mcp_client` is set, the tool is a thin shim around an
    # MCP server's `tools/call`. The dispatcher checks this attribute and
    # routes through `_call_mcp` instead of calling `handler` directly.
    # The circuit-breaker check still happens at the dispatcher level.
    mcp_client: Any = None
    mcp_server_name: str | None = None


class ToolRegistry:
    """Holds all registered tools, supports enable/disable, and dispatches calls.

    If `auto_discover=True` is passed to `__init__`, all builtin tools are
    registered as a side effect of constructing the registry. This is opt-in
    (off by default for the shared `registry` singleton to keep import order
    predictable; on by default in CLI/server bootstrap paths).
    """

    def __init__(self, *, auto_discover: bool = False) -> None:
        self._tools: dict[str, _RegisteredTool] = {}
        self._toolsets: dict[str, list[str]] = {}
        self._enabled: set[str] = set()
        self._disabled: set[str] = set()  # explicit disables override default-enabled
        self._confirmation_cache: dict[str, set[str]] = {}
        self._auto_discover_done: bool = False
        # v0.2 Day 6: reverse map MCP-client (by id) → set of remote tool names
        # we registered from it, so `unregister_mcp_server(client)` can cleanly
        # remove the whole bundle.
        self._mcp_clients: dict[int, set[str]] = {}
        if auto_discover:
            self.auto_discover()

    def auto_discover(self) -> None:
        """Register all builtin tools into this registry. Idempotent."""
        if self._auto_discover_done:
            return
        try:
            from hello_agent.tools.builtin._register import register_all
        except Exception as exc:  # noqa: BLE001 — best-effort discovery
            # Builtins might not be importable in minimal test envs. Don't crash.
            _logger.debug("builtin auto-discover failed: %s", exc)
            self._auto_discover_done = True
            return
        register_all(self)
        self._auto_discover_done = True

    # --- registration ---

    @classmethod
    def register_static(
        cls,
        name: str,
        toolset: str,
        schema: ToolDefinition,
        handler: Callable[..., ToolResult],
        check_fn: Callable[[], bool] | None = None,
        requires_env: list[str] | None = None,
        dangerous: bool = False,
    ) -> None:
        """Static registration — used by the @tool decorator and bootstrap modules.

        The shared `registry` singleton receives all such registrations. Tests
        typically build their own `ToolRegistry` instance instead.
        """
        registry._tools[name] = _RegisteredTool(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=handler,
            check_fn=check_fn,
            requires_env=requires_env or [],
            dangerous=dangerous,
        )
        registry._toolsets.setdefault(toolset, []).append(name)
        registry._enabled.add(name)  # default-enabled

    def register(
        self,
        name: str,
        toolset: str,
        schema: ToolDefinition,
        handler: Callable[..., ToolResult],
        check_fn: Callable[[], bool] | None = None,
        requires_env: list[str] | None = None,
        dangerous: bool = False,
        mcp_client: Any = None,
        mcp_server_name: str | None = None,
    ) -> None:
        self._tools[name] = _RegisteredTool(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=handler,
            check_fn=check_fn,
            requires_env=requires_env or [],
            dangerous=dangerous,
            mcp_client=mcp_client,
            mcp_server_name=mcp_server_name,
        )
        self._toolsets.setdefault(toolset, []).append(name)
        self._enabled.add(name)

    # --- MCP integration (v0.2 Day 6) ---

    def register_mcp_server(self, client: Any) -> list[str]:
        """Merge a remote MCP server's tools into this registry.

        `client` is an `MCPClient` (lazy-imported in `protocols.mcp_client`).
        Each tool the server exposes becomes a local `_RegisteredTool` whose
        `mcp_client` is set; `execute()` routes the call through
        `_call_mcp`, and the per-tool circuit breaker is consulted on every
        invocation (so a flapping remote server trips the breaker just like
        a flaky local tool).

        Returns the list of registered tool names.

        Idempotency: re-registering the same client replaces any previously
        registered tools from that client (matched by `id(client)`).
        """
        if client is None:
            raise ValueError("register_mcp_server: client is None")
        # Drop any prior registration from this client (idempotent re-register).
        self.unregister_mcp_server(client)

        client_id = id(client)
        # `list_tools()` performs the JSON-RPC `tools/list` round-trip.
        # We require the client to be connected; if not, raise clearly.
        if not getattr(client, "connected", False):
            try:
                client.connect()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"register_mcp_server: client {getattr(client, 'name', '?')!r} "
                    f"failed to connect: {exc}"
                ) from exc
        tools = client.list_tools()
        server_name = getattr(client, "name", "external")
        toolset_name = f"mcp:{server_name}"
        registered: list[str] = []
        for tool in tools:
            tname = str(tool.get("name") or "").strip()
            if not tname:
                continue
            # Skip if a local tool already has this name — local wins.
            if tname in self._tools:
                _logger.debug(
                    "register_mcp_server: skipping %r — already registered locally", tname
                )
                continue
            schema = ToolDefinition(
                name=tname,
                description=str(tool.get("description") or ""),
                parameters=dict(tool.get("inputSchema") or {"type": "object"}),
            )
            # The `handler` is never actually called for remote tools — the
            # dispatcher checks `mcp_client` and routes through `_call_mcp`.
            # We still provide a fallback that errors out clearly, in case
            # someone calls the handler directly. Bind `tname` via default
            # arg to avoid late-binding loop variable (ruff B023).

            def _fallback(
                args: dict[str, Any],
                *,
                _tname: str = tname,
                **kw: Any,
            ) -> ToolResult:  # pragma: no cover
                return ToolResult(
                    tool_call_id=kw.get("tool_call_id", ""),
                    content=f'{{"error": "tool {_tname!r} is MCP-backed; call execute() not handler"}}',
                    is_error=True,
                )

            self.register(
                name=tname,
                toolset=toolset_name,
                schema=schema,
                handler=_fallback,
                mcp_client=client,
                mcp_server_name=server_name,
            )
            registered.append(tname)
        self._mcp_clients[client_id] = set(registered)
        _logger.info(
            "register_mcp_server: %s — registered %d remote tools: %s",
            server_name, len(registered), registered,
        )
        return registered

    def unregister_mcp_server(self, client: Any) -> int:
        """Remove every tool previously registered from `client`. Returns count."""
        if client is None:
            return 0
        names = list(self._mcp_clients.pop(id(client), set()))
        for n in names:
            self.unregister(n)
        return len(names)

    def unregister(self, name: str) -> bool:
        """Remove a tool from the registry. Returns True if it existed.

        Idempotent: re-unregistering a missing tool is a no-op (returns False).
        Also drops the tool from its toolset list and clears any per-session
        confirmation entries for it.
        """
        if name not in self._tools:
            return False
        entry = self._tools.pop(name)
        # Drop from toolset membership
        bucket = self._toolsets.get(entry.toolset)
        if bucket is not None:
            try:
                bucket.remove(name)
            except ValueError:
                pass
        self._enabled.discard(name)
        self._disabled.discard(name)
        # Drop any per-session confirmations
        for cache in self._confirmation_cache.values():
            cache.discard(name)
        # v0.2 Day 6: also drop from any MCP reverse-map entry
        for client_id, names in list(self._mcp_clients.items()):
            names.discard(name)
            if not names:
                self._mcp_clients.pop(client_id, None)
        return True

    def register_toolset(
        self,
        name: str,
        tool_names: list[str],
        inherits_from: list[str] | None = None,
    ) -> None:
        inherited: list[str] = list(tool_names)
        for parent in inherits_from or []:
            inherited.extend(self._toolsets.get(parent, []))
        # Dedupe while preserving order
        seen: set[str] = set()
        merged: list[str] = []
        for t in inherited:
            if t not in seen:
                seen.add(t)
                merged.append(t)
        self._toolsets[name] = merged

    # --- enable / disable ---

    def enable(self, tool_names: list[str]) -> None:
        for n in tool_names:
            self._disabled.discard(n)
            if n in self._tools:
                self._enabled.add(n)

    def disable(self, tool_names: list[str]) -> None:
        for n in tool_names:
            self._disabled.add(n)
            self._enabled.discard(n)

    def is_enabled(self, tool_name: str) -> bool:
        if tool_name in self._disabled:
            return False
        return tool_name in self._enabled

    # --- listing ---

    def list_all(self) -> list[_RegisteredTool]:
        return list(self._tools.values())

    # `list()` is the day-2 spec name; `list_all()` kept for back-compat.
    list = list_all  # type: ignore[assignment]

    def list_tool_definitions(self, enabled_only: bool = True) -> list[ToolDefinition]:
        out: list[ToolDefinition] = []
        for name, t in self._tools.items():
            if enabled_only and not self.is_enabled(name):
                continue
            out.append(t.schema)
        return out

    def filter_by_profile(
        self,
        profile: str,
        *,
        enabled_only: bool = False,
    ) -> list[_RegisteredTool]:
        """Return the tools registered under the given toolset/profile name.

        Resolution order:
          1. If `profile` matches a registered toolset (e.g. "default", "react"),
             return those tools in the order they were registered.
          2. Otherwise, return every tool whose `toolset` field matches `profile`.
          3. If nothing matches, return an empty list (never raises).

        `enabled_only=True` further filters out disabled tools. This is the
        per-agent filter used by the CLI / runtime when a profile like
        `default` / `react` / `plan_solve` is selected.
        """
        members: list[str] = []
        if profile in self._toolsets:
            members = list(self._toolsets[profile])
        else:
            for t in self._tools.values():
                if t.toolset == profile:
                    members.append(t.name)
        out: list[_RegisteredTool] = []
        seen: set[str] = set()
        for n in members:
            if n in seen:
                continue
            if n not in self._tools:
                continue
            if enabled_only and not self.is_enabled(n):
                continue
            out.append(self._tools[n])
            seen.add(n)
        return out

    def get(self, name: str) -> _RegisteredTool:
        if name not in self._tools:
            raise ToolNotFoundError(name, f"not registered (have: {sorted(self._tools.keys())})")
        return self._tools[name]

    # --- dispatch ---

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        session_id: str | None = None,
        tool_call_id: str = "",
    ) -> ToolResult:
        tool = self.get(name)
        if not self.is_enabled(name):
            return ToolResult(
                tool_call_id=tool_call_id,
                content=f"{{\"error\": \"tool '{name}' is disabled\"}}",
                is_error=True,
            )
        if tool.dangerous and session_id is not None:
            if not self.is_confirmed(session_id, name):
                return ToolResult(
                    tool_call_id=tool_call_id,
                    content=(
                        f"{{\"error\": \"tool '{name}' requires confirmation. "
                        f"Run /confirm {name} or remove from require_confirmation in config.\"}}"
                    ),
                    is_error=True,
                )

        # v0.2 Day 6: MCP-backed tools route through `_call_mcp` and the
        # circuit breaker is consulted just like for local tools.
        if tool.mcp_client is not None:
            if not check_breaker(name):
                raise CircuitOpenError(
                    name,
                    "circuit breaker open (MCP server flapping); refusing call",
                )
            try:
                result = self._call_mcp(tool, name, arguments, tool_call_id=tool_call_id)
            except Exception as exc:  # noqa: BLE001
                # Connection-level errors trip the breaker; surface a
                # stringified error result the same way local handlers do.
                record_failure(name)
                return ToolResult(
                    tool_call_id=tool_call_id,
                    content=f"{{\"error\": \"{type(exc).__name__}: {exc}\"}}",
                    is_error=True,
                )
            if result.is_error:
                # Remote tool reported failure (e.g. invalid args) — count it.
                record_failure(name)
            else:
                record_success(name)
            return ToolResult(
                tool_call_id=tool_call_id,
                content=result.text,
                is_error=result.is_error,
            )

        return tool.handler(arguments, session_id=session_id, tool_call_id=tool_call_id)

    def _call_mcp(
        self,
        tool: _RegisteredTool,
        name: str,
        arguments: dict[str, Any],
        *,
        tool_call_id: str = "",
    ) -> Any:
        """Invoke a remote MCP tool and return its `MCPCallResult`.

        Defined on the registry (not on `MCPClient`) so the lazy import of
        `protocols.mcp_client` stays out of the registry's import surface.
        `tool.mcp_client` is the live `MCPClient` instance; it already
        carries a connected stdio session.
        """
        # Lazy import — the registry is imported widely; the MCP SDK is optional.
        from hello_agent.protocols.mcp_client import MCPCallResult

        client = tool.mcp_client
        # Re-connect transparently if the user closed + reconnected the client.
        if not getattr(client, "connected", False):
            client.connect()
        result = client.call_tool(name, arguments)
        if not isinstance(result, MCPCallResult):
            # Defensive: future SDK return shapes; coerce.
            return MCPCallResult(text=str(result), is_error=True)
        return result

    # --- confirmation ---

    def is_confirmed(self, session_id: str, tool_name: str) -> bool:
        return tool_name in self._confirmation_cache.get(session_id, set())

    def confirm_dangerous(self, session_id: str, tool_name: str) -> None:
        self._confirmation_cache.setdefault(session_id, set()).add(tool_name)


# Module-level shared registry — populated by `@tool` decorator and bootstrap imports.
registry = ToolRegistry()
