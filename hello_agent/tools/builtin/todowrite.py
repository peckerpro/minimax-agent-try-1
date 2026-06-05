"""todowrite — in-session task list.

Agent-level: each session has its own list. The state lives in the tool
itself (module-level dict keyed by session_id). On session end the list is
discarded unless explicitly exported.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from hello_agent.core.types import ToolDefinition, ToolResponse, ToolResult
from hello_agent.tools.registry import ToolRegistry

_SESSION_TODOS: dict[str, list[dict[str, Any]]] = {}


def _normalize(item: Any) -> dict[str, Any]:
    """Accept either a dict or a flat string for `content`."""
    if isinstance(item, dict):
        return {
            "id": item.get("id") or uuid.uuid4().hex[:8],
            "content": item.get("content", ""),
            "status": item.get("status", "pending"),
            "active_form": item.get("active_form", ""),
            "updated_at": time.time(),
        }
    return {
        "id": uuid.uuid4().hex[:8],
        "content": str(item),
        "status": "pending",
        "active_form": "",
        "updated_at": time.time(),
    }


def _todowrite(args: dict[str, Any]) -> ToolResponse:
    items = args.get("items", [])
    if not isinstance(items, list):
        return ToolResponse.fail("`items` must be a list")
    session_id = args.get("session_id", "default")
    normalized = [_normalize(i) for i in items]
    _SESSION_TODOS[session_id] = normalized
    return ToolResponse.ok({"todos": normalized, "session_id": session_id})


def get_todos(session_id: str) -> list[dict[str, Any]]:
    return list(_SESSION_TODOS.get(session_id, []))


def clear_todos(session_id: str) -> None:
    _SESSION_TODOS.pop(session_id, None)


def _to_result(response: ToolResponse, tool_call_id: str) -> ToolResult:
    content = (
        response.data
        if isinstance(response.data, str)
        else (response.to_json() if response.data is not None else "")
    )
    return ToolResult(tool_call_id=tool_call_id, content=content, is_error=not response.success)


def register(registry: ToolRegistry) -> None:
    registry.register(
        name="todowrite",
        toolset="meta",
        schema=ToolDefinition(
            name="todowrite",
            description="Update the in-session task list. Items: {content, status, active_form}.",
            parameters={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                                "active_form": {"type": "string"},
                            },
                            "required": ["content"],
                        },
                    },
                    "session_id": {"type": "string"},
                },
                "required": ["items"],
            },
        ),
        handler=lambda args, **kw: _to_result(_todowrite(args), kw.get("tool_call_id", "")),
    )
