"""notify — desktop / Windows toast notification.

On Windows uses `windows-toasts` if installed; otherwise falls back to a
loguru warning. On non-Windows, no-op with a log line.
"""
from __future__ import annotations

from typing import Any

from hello_agent.core.logging import get_logger
from hello_agent.core.types import ToolDefinition, ToolResponse, ToolResult
from hello_agent.tools.registry import ToolRegistry

logger = get_logger(__name__)


def _notify(args: dict[str, Any]) -> ToolResponse:
    title = args.get("title", "hello-agent")
    body = args.get("body", "")
    if not body:
        return ToolResponse.fail("body is required")
    if not title:
        title = "hello-agent"

    if _try_windows_toast(title, body):
        return ToolResponse.ok({"delivered": "windows-toast"})

    # Fallback: log line
    logger.info("[notify] {}: {}", title, body)
    return ToolResponse.ok({"delivered": "log", "title": title, "body": body})


def _try_windows_toast(title: str, body: str) -> bool:
    try:
        from windows_toasts import Toast, WindowsToaster  # type: ignore[import-not-found]

        toaster = WindowsToaster("hello-agent")
        toast = Toast()
        toast.text_fields = [title, body]
        toaster.show_toast(toast)
        return True
    except Exception:  # noqa: BLE001
        return False


def _to_result(response: ToolResponse, tool_call_id: str) -> ToolResult:
    content = (
        response.data
        if isinstance(response.data, str)
        else (response.to_json() if response.data is not None else "")
    )
    return ToolResult(tool_call_id=tool_call_id, content=content, is_error=not response.success)


def register(registry: ToolRegistry) -> None:
    registry.register(
        name="notify",
        toolset="meta",
        schema=ToolDefinition(
            name="notify",
            description="Show a desktop / Windows toast notification.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["body"],
            },
        ),
        handler=lambda args, **kw: _to_result(_notify(args), kw.get("tool_call_id", "")),
    )
