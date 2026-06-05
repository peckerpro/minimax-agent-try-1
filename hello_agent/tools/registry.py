"""Tool auto-discovery + dispatch.

Borrowed from `NousResearch/hermes-agent/tools/registry.py` with:
- Added `dangerous` flag for confirmation-gated tools
- Added per-session confirmation cache
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hello_agent.core.exceptions import ToolNotFoundError
from hello_agent.core.types import ToolDefinition, ToolResult


@dataclass
class _RegisteredTool:
    name: str
    toolset: str
    schema: ToolDefinition
    handler: Callable[..., ToolResult]
    check_fn: Callable[[], bool] | None = None
    requires_env: list[str] = field(default_factory=list)
    dangerous: bool = False


class ToolRegistry:
    """Holds all registered tools, supports enable/disable, and dispatches calls."""

    def __init__(self) -> None:
        self._tools: dict[str, _RegisteredTool] = {}
        self._toolsets: dict[str, list[str]] = {}
        self._enabled: set[str] = set()
        self._disabled: set[str] = set()  # explicit disables override default-enabled
        self._confirmation_cache: dict[str, set[str]] = {}

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
    ) -> None:
        self._tools[name] = _RegisteredTool(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=handler,
            check_fn=check_fn,
            requires_env=requires_env or [],
            dangerous=dangerous,
        )
        self._toolsets.setdefault(toolset, []).append(name)
        self._enabled.add(name)

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

    def list_tool_definitions(self, enabled_only: bool = True) -> list[ToolDefinition]:
        out: list[ToolDefinition] = []
        for name, t in self._tools.items():
            if enabled_only and not self.is_enabled(name):
                continue
            out.append(t.schema)
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
        return tool.handler(arguments, session_id=session_id, tool_call_id=tool_call_id)

    # --- confirmation ---

    def is_confirmed(self, session_id: str, tool_name: str) -> bool:
        return tool_name in self._confirmation_cache.get(session_id, set())

    def confirm_dangerous(self, session_id: str, tool_name: str) -> None:
        self._confirmation_cache.setdefault(session_id, set()).add(tool_name)


# Module-level shared registry — populated by `@tool` decorator and bootstrap imports.
registry = ToolRegistry()
