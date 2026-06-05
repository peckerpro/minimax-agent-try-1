"""Permission gate for dangerous tools.

Two layers:
1. Global allowlist of tool names that ALWAYS require confirmation
   (sourced from `ToolsConfig.require_confirmation`).
2. Per-session confirmation cache — once a user confirms a dangerous tool in
   a given session, it can run unattended for the rest of the session.

The check itself is delegated to the registry's `is_confirmed()` method.
"""
from __future__ import annotations

from hello_agent.core.config import get_config
from hello_agent.tools.registry import registry


def _requires_confirmation(tool_name: str) -> bool:
    cfg = get_config()
    # Match by exact name OR `toolset.tool_name` form.
    candidates = {tool_name}
    if "." in tool_name:
        candidates.add(tool_name.split(".", 1)[1])
    for entry in cfg.tools.require_confirmation:
        if entry in candidates:
            return True
        if entry == tool_name:
            return True
    return False


def check_permission(tool_name: str, session_id: str | None) -> bool:
    """Return True if the tool is OK to run for this session."""
    if not _requires_confirmation(tool_name):
        return True
    if session_id is None:
        return False
    return registry.is_confirmed(session_id, tool_name)


def confirm_in_session(session_id: str, tool_name: str) -> None:
    """Mark a dangerous tool as confirmed for this session."""
    registry.confirm_dangerous(session_id, tool_name)


def list_dangerous_tools() -> list[str]:
    """Return all tool names that the registry knows are dangerous."""
    out: list[str] = []
    for tool in registry.list_all():
        if tool.dangerous:
            out.append(tool.name)
    return sorted(set(out))
