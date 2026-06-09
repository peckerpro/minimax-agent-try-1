"""Tools route — list / enable / disable.

A "tool" here is anything registered with `hello_agent.tools.registry`.
The list endpoint surfaces the full schema (name, toolset, dangerous
flag, JSON Schema for parameters) so the React UI can render a
toggleable table. Enable/disable mutates the shared registry in place
— the changes are visible to every subsequent `agent.step()` call.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hello_agent.core.logging import get_logger
from hello_agent.tools.registry import registry

logger = get_logger(__name__)

router = APIRouter()


# ----- response models --------------------------------------------------------


class ToolInfo(BaseModel):
    name: str
    toolset: str
    enabled: bool
    dangerous: bool = False
    description: str = ""
    requires_env: list[str] = []
    parameters: dict[str, Any] = {}


class ToolToggleResponse(BaseModel):
    name: str
    enabled: bool


# ----- helpers ----------------------------------------------------------------


def _tool_to_dict(t: Any) -> dict[str, Any]:
    """Project a `_RegisteredTool` into the wire shape.

    `t` is a private type (`_RegisteredTool`) from the registry; we
    duck-type rather than import the private class so the route
    module doesn't break if the registry renames it.
    """
    return {
        "name": t.name,
        "toolset": t.toolset,
        "enabled": registry.is_enabled(t.name),
        "dangerous": bool(t.dangerous),
        "description": t.schema.description,
        "requires_env": list(t.requires_env or []),
        "parameters": dict(t.schema.parameters or {}),
    }


# ----- routes -----------------------------------------------------------------


@router.get("/", response_model=list[ToolInfo])
async def list_all(include_disabled: bool = True) -> list[ToolInfo]:
    """List every registered tool. `include_disabled=False` hides OFF tools."""
    tools = registry.list_all()
    out: list[ToolInfo] = []
    for t in tools:
        info = _tool_to_dict(t)
        if not include_disabled and not info["enabled"]:
            continue
        out.append(ToolInfo(**info))
    return out


@router.post("/{name}/enable", response_model=ToolToggleResponse)
async def enable(name: str) -> ToolToggleResponse:
    """Enable a tool by name. 404 if not registered."""
    if name not in {t.name for t in registry.list_all()}:
        raise HTTPException(status_code=404, detail=f"tool {name!r} not registered")
    registry.enable([name])
    return ToolToggleResponse(name=name, enabled=registry.is_enabled(name))


@router.post("/{name}/disable", response_model=ToolToggleResponse)
async def disable(name: str) -> ToolToggleResponse:
    """Disable a tool by name. 404 if not registered."""
    if name not in {t.name for t in registry.list_all()}:
        raise HTTPException(status_code=404, detail=f"tool {name!r} not registered")
    registry.disable([name])
    return ToolToggleResponse(name=name, enabled=registry.is_enabled(name))


__all__ = ["router", "ToolInfo", "ToolToggleResponse"]
