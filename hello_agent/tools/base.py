"""Tool ABC + `@tool` decorator.

The decorator builds a JSON-Schema `parameters` dict from the function signature
(using `inspect.signature` + type hints) and registers a `_RegisteredTool`
entry into the shared `ToolRegistry`.
"""
from __future__ import annotations

import functools
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import field
from typing import Any, Optional, get_args, get_origin, get_type_hints

from hello_agent.core.exceptions import ToolNotFoundError, ToolPermissionDeniedError
from hello_agent.core.types import ToolDefinition, ToolResponse, ToolResult

# ----- Schema generation from type hints -----


_PRIMITIVE_JSON_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    type(None): "null",
}


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
    """Best-effort conversion of a Python type annotation to a JSON-Schema fragment."""
    if annotation is inspect.Parameter.empty or annotation is None:
        return {"type": "string"}
    if isinstance(annotation, type) and annotation in _PRIMITIVE_JSON_TYPES:
        return {"type": _PRIMITIVE_JSON_TYPES[annotation]}
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        if args:
            return {"type": "array", "items": _annotation_to_schema(args[0])}
        return {"type": "array"}
    if origin is dict:
        return {"type": "object", "additionalProperties": True}
    if origin is Optional or origin is type(None):  # Optional[X] -> X
        args = get_args(annotation)
        if args:
            return _annotation_to_schema(args[0])
    if isinstance(annotation, type):
        return {"type": "string"}  # fall back to string for unknown classes
    return {"type": "string"}


def _signature_to_parameters(fn: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON-Schema object from the function's signature."""
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:  # noqa: BLE001
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name == "self":
            continue
        annotation = hints.get(name, param.annotation)
        prop: dict[str, Any] = _annotation_to_schema(annotation)
        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(name)
        properties[name] = prop

    return {"type": "object", "properties": properties, "required": required}


# ----- Tool ABC -----


class Tool(ABC):
    """Base class for object-style tools. Use the `@tool` decorator for functions."""

    name: str = ""
    description: str = ""
    toolset: str = "default"
    dangerous: bool = False
    requires_env: list[str] = field(default_factory=list)

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResponse:
        ...


# ----- @tool decorator -----


def tool(
    name: str | None = None,
    description: str | None = None,
    toolset: str = "default",
    dangerous: bool = False,
    requires_env: list[str] | None = None,
    check_fn: Callable[[], bool] | None = None,
):
    """Decorator: turn a function into a registered tool.

    Usage:
        @tool(description="Read a file", dangerous=False)
        def read_file(path: str) -> ToolResponse:
            return ToolResponse.ok(path.read_text(encoding="utf-8"))
    """
    from hello_agent.tools.registry import ToolRegistry

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or fn.__name__
        tool_desc = description or (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else tool_name
        schema = ToolDefinition(
            name=tool_name,
            description=tool_desc,
            parameters=_signature_to_parameters(fn),
            requires_confirmation=dangerous,
        )

        def handler(args: dict[str, Any], session_id: str | None = None, **kw: Any) -> ToolResult:
            try:
                response: ToolResponse = fn(**args)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(
                    tool_call_id=kw.get("tool_call_id", ""),
                    content=f"{{\"error\": \"{type(exc).__name__}: {exc}\"}}",
                    is_error=True,
                )
            content = (
                response.data
                if isinstance(response.data, str)
                else (response.to_json() if response.data is not None else "")
            )
            return ToolResult(
                tool_call_id=kw.get("tool_call_id", ""),
                content=content,
                is_error=not response.success,
                truncated=bool(response.hint and "truncated" in response.hint.lower()),
            )

        ToolRegistry.register_static(
            name=tool_name,
            toolset=toolset,
            schema=schema,
            handler=handler,
            check_fn=check_fn,
            requires_env=requires_env or [],
            dangerous=dangerous,
        )

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper._is_hello_agent_tool = True  # type: ignore[attr-defined]
        wrapper._tool_name = tool_name  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ----- Module-level re-exports (used elsewhere) -----

__all__ = ["Tool", "tool", "ToolDefinition", "ToolResponse", "ToolResult",
           "ToolNotFoundError", "ToolPermissionDeniedError"]
