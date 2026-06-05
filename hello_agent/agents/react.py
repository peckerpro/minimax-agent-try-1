"""ReAct — Reasoning + Acting agent loop. Default agent type.

The classic ReAct pattern:
  loop:
    1. LLM call with current messages + available tool schemas
    2. If LLM emits tool_calls, dispatch each tool and append a tool result message
    3. If no tool_calls, the LLM's reply is the final answer → done

Borrowed shape from `NousResearch/hermes-agent/run_agent.py`, simplified.
"""
from __future__ import annotations

import json

from hello_agent.agents.base import Agent
from hello_agent.core.exceptions import (
    CircuitOpenError,
    ToolNotFoundError,
    ToolPermissionDeniedError,
)
from hello_agent.core.llm import LLMClient
from hello_agent.core.logging import get_logger
from hello_agent.core.types import AgentState, Message, Role, ToolCall, ToolResult
from hello_agent.tools.registry import ToolRegistry

logger = get_logger(__name__)


class ReActAgent(Agent):
    """Reasoning + Acting loop. The default agent type."""

    def __init__(
        self,
        llm: LLMClient,
        tool_registry: ToolRegistry,
        system_prompt: str = "You are a helpful personal assistant running on the user's Windows machine.",
        max_iterations: int = 30,
        max_cost_per_turn_usd: float = 0.50,
        session_id: str | None = None,
    ):
        super().__init__(
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            max_cost_per_turn_usd=max_cost_per_turn_usd,
            session_id=session_id,
        )
        self.llm = llm
        self.tool_registry = tool_registry

    def step(self, state: AgentState) -> AgentState:
        # 1. Call LLM with current messages + available tool schemas
        tool_defs = self.tool_registry.list_tool_definitions(enabled_only=True)
        try:
            response = self.llm.chat(
                messages=state.messages,
                tools=tool_defs if tool_defs else None,
            )
        except Exception as exc:  # noqa: BLE001 — log and bubble up to run()
            logger.error("LLM call failed: {}", exc)
            raise

        choice = response.choices[0]
        assistant_msg = choice.message

        # 2. Append assistant message (may include tool_calls)
        tool_calls: list[ToolCall] = []
        if assistant_msg.tool_calls:
            for tc in assistant_msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        state.messages.append(
            Message(
                role=Role.ASSISTANT,
                content=assistant_msg.content,
                tool_calls=tool_calls or None,
                finish_reason=choice.finish_reason,
                token_count=response.usage.total_tokens if response.usage else None,
            )
        )

        # 3. If no tool calls, we're done.
        if not tool_calls:
            return state

        # 4. Execute each tool call, append a tool result message
        for tc in tool_calls:
            result = self._dispatch_tool(tc)
            state.messages.append(
                Message(
                    role=Role.TOOL,
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=result.content,
                )
            )

        return state

    def _dispatch_tool(self, tc: ToolCall) -> ToolResult:
        """Permission check + circuit breaker + dispatch. Returns a ToolResult (never raises)."""
        from hello_agent.tools.circuit_breaker import check_breaker, record_failure, record_success
        from hello_agent.tools.permission import check_permission

        if not check_permission(tc.name, self.session_id):
            return ToolResult(
                tool_call_id=tc.id,
                content=json.dumps(
                    {"error": "Permission denied", "tool": tc.name},
                    ensure_ascii=False,
                ),
                is_error=True,
            )

        if not check_breaker(tc.name):
            return ToolResult(
                tool_call_id=tc.id,
                content=json.dumps(
                    {"error": "Circuit open (too many recent failures)"},
                    ensure_ascii=False,
                ),
                is_error=True,
            )

        try:
            result = self.tool_registry.execute(
                tc.name, tc.arguments, session_id=self.session_id
            )
        except (ToolNotFoundError, ToolPermissionDeniedError, CircuitOpenError) as exc:
            record_failure(tc.name)
            return ToolResult(
                tool_call_id=tc.id,
                content=json.dumps({"error": str(exc)}, ensure_ascii=False),
                is_error=True,
            )
        except Exception as exc:  # noqa: BLE001
            record_failure(tc.name)
            logger.exception("Tool {} failed", tc.name)
            return ToolResult(
                tool_call_id=tc.id,
                content=json.dumps(
                    {"error": f"{type(exc).__name__}: {exc}"},
                    ensure_ascii=False,
                ),
                is_error=True,
            )

        if result.success:
            record_success(tc.name)
        else:
            record_failure(tc.name)

        # The LLM wants a string back. ToolResponse.ok data is `Any`; stringify nicely.
        content = (
            result.data
            if isinstance(result.data, str)
            else json.dumps(result.data, ensure_ascii=False, default=str)
        )
        return ToolResult(
            tool_call_id=tc.id,
            content=content,
            is_error=not result.success,
            truncated=bool(result.hint and "truncated" in result.hint.lower()),
        )
