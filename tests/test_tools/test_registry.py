"""Tests for hello_agent.tools.registry.ToolRegistry."""
from __future__ import annotations

import pytest

from hello_agent.core.exceptions import ToolNotFoundError
from hello_agent.core.types import ToolDefinition, ToolResult
from hello_agent.tools.registry import ToolRegistry


def _echo_schema(name: str = "echo", description: str = "echoes input") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )


def _make_handler(prefix: str = "echo:"):
    def handler(args: dict, **kw: object) -> ToolResult:
        return ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=f"{prefix}{args.get('text', '')}",
        )

    return handler


# --- register / get / list --------------------------------------------------


def test_fresh_registry_is_empty() -> None:
    """A fresh ToolRegistry has no tools until you register one."""
    reg = ToolRegistry()
    assert reg.list() == []
    assert reg.list_tool_definitions() == []


def test_register_adds_to_list_and_get() -> None:
    """After register(), the tool appears in list() and is retrievable via get()."""
    reg = ToolRegistry()
    reg.register(name="echo", toolset="smoke", schema=_echo_schema(), handler=_make_handler())

    names = [t.name for t in reg.list()]
    assert names == ["echo"]

    entry = reg.get("echo")
    assert entry.name == "echo"
    assert entry.toolset == "smoke"
    assert entry.schema.name == "echo"
    assert entry.dangerous is False


def test_register_dangerous_marks_entry() -> None:
    """`dangerous=True` is stored on the registered entry."""
    reg = ToolRegistry()
    reg.register(
        name="risky",
        toolset="smoke",
        schema=_echo_schema("risky", "risky op"),
        handler=_make_handler(),
        dangerous=True,
    )
    assert reg.get("risky").dangerous is True


def test_get_missing_raises_tool_not_found() -> None:
    """`get()` on a missing name raises `ToolNotFoundError`."""
    reg = ToolRegistry()
    with pytest.raises(ToolNotFoundError, match="nope"):
        reg.get("nope")


# --- unregister -------------------------------------------------------------


def test_unregister_removes_entry() -> None:
    """`unregister()` returns True and the tool is gone afterwards."""
    reg = ToolRegistry()
    reg.register(name="echo", toolset="smoke", schema=_echo_schema(), handler=_make_handler())
    assert reg.unregister("echo") is True
    assert reg.list() == []


def test_unregister_is_idempotent() -> None:
    """Re-unregistering a missing tool returns False (no exception)."""
    reg = ToolRegistry()
    assert reg.unregister("echo") is False
    assert reg.unregister("echo") is False


def test_unregister_clears_session_confirmations() -> None:
    """`unregister()` must drop the tool from any per-session confirmation cache."""
    reg = ToolRegistry()
    reg.register(
        name="risky",
        toolset="smoke",
        schema=_echo_schema("risky", "risky op"),
        handler=_make_handler(),
        dangerous=True,
    )
    reg.confirm_dangerous("sess-A", "risky")
    reg.confirm_dangerous("sess-B", "risky")
    assert reg.is_confirmed("sess-A", "risky")

    reg.unregister("risky")
    assert not reg.is_confirmed("sess-A", "risky")
    assert not reg.is_confirmed("sess-B", "risky")


def test_unregister_drops_toolset_membership() -> None:
    """`unregister()` removes the tool from its toolset's member list."""
    reg = ToolRegistry()
    reg.register(name="a", toolset="grp", schema=_echo_schema("a", "a"), handler=_make_handler())
    reg.register(name="b", toolset="grp", schema=_echo_schema("b", "b"), handler=_make_handler())
    reg.register_toolset("grouped", ["a", "b"])
    assert "a" in reg._toolsets["grp"]
    assert "b" in reg._toolsets["grp"]

    reg.unregister("a")
    assert "a" not in reg._toolsets["grp"]
    assert "b" in reg._toolsets["grp"]


# --- list() is the day-2 spec name for list_all() --------------------------


def test_list_is_alias_of_list_all() -> None:
    """`ToolRegistry.list` and `ToolRegistry.list_all` return the same view."""
    reg = ToolRegistry()
    reg.register(name="x", toolset="t", schema=_echo_schema("x", "x"), handler=_make_handler())
    assert reg.list() == reg.list_all()


# --- filter_by_profile ------------------------------------------------------


def test_filter_by_profile_returns_tools_in_toolset() -> None:
    """`filter_by_profile(name)` returns the tools in the named toolset."""
    reg = ToolRegistry()
    reg.register(name="a", toolset="alpha", schema=_echo_schema("a", "a"), handler=_make_handler())
    reg.register(name="b", toolset="alpha", schema=_echo_schema("b", "b"), handler=_make_handler())
    reg.register(name="c", toolset="beta", schema=_echo_schema("c", "c"), handler=_make_handler())

    alpha = reg.filter_by_profile("alpha")
    assert {t.name for t in alpha} == {"a", "b"}
    beta = reg.filter_by_profile("beta")
    assert {t.name for t in beta} == {"c"}


def test_filter_by_profile_returns_empty_for_unknown_profile() -> None:
    """An unknown profile yields an empty list (never raises)."""
    reg = ToolRegistry()
    reg.register(name="a", toolset="alpha", schema=_echo_schema("a", "a"), handler=_make_handler())
    assert reg.filter_by_profile("does-not-exist") == []


def test_filter_by_profile_via_register_toolset() -> None:
    """`filter_by_profile` resolves names registered via `register_toolset`."""
    reg = ToolRegistry()
    reg.register(name="a", toolset="t", schema=_echo_schema("a", "a"), handler=_make_handler())
    reg.register(name="b", toolset="t", schema=_echo_schema("b", "b"), handler=_make_handler())
    reg.register_toolset("selected", ["a", "b"])
    members = reg.filter_by_profile("selected")
    assert {t.name for t in members} == {"a", "b"}


def test_filter_by_profile_with_enabled_only() -> None:
    """`filter_by_profile(..., enabled_only=True)` skips disabled tools."""
    reg = ToolRegistry()
    reg.register(name="a", toolset="t", schema=_echo_schema("a", "a"), handler=_make_handler())
    reg.register(name="b", toolset="t", schema=_echo_schema("b", "b"), handler=_make_handler())
    reg.disable(["b"])
    members = reg.filter_by_profile("t", enabled_only=True)
    assert {t.name for t in members} == {"a"}


# --- execute / enable / disable --------------------------------------------


def test_execute_runs_handler_and_returns_result() -> None:
    """`execute()` invokes the handler and packages the result as a ToolResult."""
    reg = ToolRegistry()
    reg.register(
        name="echo",
        toolset="smoke",
        schema=_echo_schema(),
        handler=_make_handler("got:"),
    )
    res = reg.execute("echo", {"text": "hello"})
    assert res.content == "got:hello"
    assert not res.is_error


def test_execute_blocks_disabled_tool() -> None:
    """A disabled tool returns an error ToolResult (does not invoke the handler)."""
    reg = ToolRegistry()
    reg.register(
        name="echo",
        toolset="smoke",
        schema=_echo_schema(),
        handler=_make_handler("should-not-run:"),
    )
    reg.disable(["echo"])
    res = reg.execute("echo", {"text": "hi"})
    assert res.is_error
    assert "disabled" in res.content


def test_execute_dangerous_requires_confirmation() -> None:
    """A dangerous tool without session confirmation returns an error result."""
    reg = ToolRegistry()
    reg.register(
        name="risky",
        toolset="smoke",
        schema=_echo_schema("risky", "risky op"),
        handler=_make_handler(),
        dangerous=True,
    )
    # Without confirmation
    res_no_confirm = reg.execute("risky", {"text": "x"}, session_id="sess-1")
    assert res_no_confirm.is_error
    assert "confirmation" in res_no_confirm.content

    # With confirmation
    reg.confirm_dangerous("sess-1", "risky")
    res_ok = reg.execute("risky", {"text": "x"}, session_id="sess-1")
    assert not res_ok.is_error


# --- auto_discover ----------------------------------------------------------


def test_auto_discover_off_by_default_keeps_empty_registry() -> None:
    """`auto_discover=False` (the default) leaves a fresh registry empty."""
    reg = ToolRegistry()
    # The shared singleton is NOT touched, so this is a private fresh instance.
    assert reg.list() == []
    assert reg._auto_discover_done is False


def test_auto_discover_populates_with_builtin_tools() -> None:
    """`auto_discover=True` populates the registry with the builtin set."""
    reg = ToolRegistry(auto_discover=True)
    names = {t.name for t in reg.list()}
    # Spot-check the day-2-mandated builtins.
    assert {"read_file", "write_file", "edit_file", "run_powershell", "run_cmd", "document_parser"} <= names
    assert reg._auto_discover_done is True
