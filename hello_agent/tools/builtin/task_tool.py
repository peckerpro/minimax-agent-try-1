"""task_tool — subagent delegation (router picks child agent type).

Borrowed shape from hermes `tools/delegate_tool.py` — single-task + batch,
role-based gating, max_concurrent_children, subagent_auto_approve. The
v0.1 implementation is intentionally minimal: it spins up a fresh
ReActAgent with a smaller iteration budget and returns its final answer.
"""
from __future__ import annotations

from typing import Any

from hello_agent.core.config import get_config
from hello_agent.core.llm import LLMClient
from hello_agent.core.logging import get_logger
from hello_agent.core.types import (
    Role,
    ToolDefinition,
    ToolResponse,
    ToolResult,
)
from hello_agent.tools.registry import ToolRegistry

logger = get_logger(__name__)


def _delegate(args: dict[str, Any]) -> ToolResponse:
    goal = args.get("goal", "")
    if not goal:
        return ToolResponse.fail("goal is required")
    role = args.get("role", "leaf")
    max_iter = int(args.get("max_iterations", 8))

    # Lazy import to avoid circular: agents → tools
    from hello_agent.agents.react import ReActAgent

    llm = LLMClient()
    cfg = get_config()
    system_prompt = (
        f"You are a subagent (role={role}). "
        "Complete the goal and respond with a concise final answer. "
        "Use tools only if strictly needed."
    )
    try:
        from hello_agent.tools.toolsets import bootstrap_toolsets  # noqa: F401
    except Exception:
        pass

    # Use a fresh tool registry for the subagent; in v0.1 we share the global one.
    from hello_agent.tools.registry import registry as global_registry  # noqa: WPS433

    agent = ReActAgent(
        llm=llm,
        tool_registry=global_registry,
        system_prompt=system_prompt,
        max_iterations=max_iter,
        max_cost_per_turn_usd=cfg.agent.max_cost_per_turn_usd,
    )
    state = agent.run(goal)
    last_assistant = next(
        (m for m in reversed(state.messages) if m.role == Role.ASSISTANT and m.content),
        None,
    )
    answer = last_assistant.content if last_assistant else ""
    return ToolResponse.ok(
        {
            "answer": answer,
            "iterations": state.iteration,
            "session_id": agent.session_id,
        }
    )


def _to_result(response: ToolResponse, tool_call_id: str) -> ToolResult:
    content = (
        response.data
        if isinstance(response.data, str)
        else (response.to_json() if response.data is not None else "")
    )
    return ToolResult(tool_call_id=tool_call_id, content=content, is_error=not response.success)


def register(registry: ToolRegistry) -> None:
    registry.register(
        name="task_delegate",
        toolset="meta",
        schema=ToolDefinition(
            name="task_delegate",
            description="Spawn a subagent (ReAct) to handle a delegated goal.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "role": {"type": "string", "description": "Subagent role label (default 'leaf')."},
                    "max_iterations": {"type": "integer", "description": "Default 8."},
                },
                "required": ["goal"],
            },
        ),
        handler=lambda args, **kw: _to_result(_delegate(args), kw.get("tool_call_id", "")),
    )
