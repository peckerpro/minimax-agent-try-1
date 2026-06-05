"""ReAct — Reasoning + Acting agent loop. Default agent type.

The classic ReAct pattern:
  loop:
    1. LLM call with current messages + available tool schemas
    2. If LLM emits tool_calls, dispatch each tool and append a tool result message
    3. If no tool_calls, the LLM's reply is the final answer → done
    4. SPECIAL: if the LLM emits a `final_answer` tool call, treat its
       `answer` argument as the final assistant reply and terminate the loop
       without dispatching any other tools in the same step.

Borrowed shape from `NousResearch/hermes-agent/run_agent.py`, simplified.
"""
from __future__ import annotations

import json
from typing import Any

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

#: Sentinel tool name. When the LLM emits a tool_call with this name, the
#: ReAct loop ends and the tool's `answer` argument becomes the final
#: assistant message.
FINAL_ANSWER_TOOL = "final_answer"


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

    # --- step -----------------------------------------------------------------

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

        # 2. Parse the assistant's tool_calls (if any) into our ToolCall dataclass.
        tool_calls: list[ToolCall] = []
        if assistant_msg.tool_calls:
            for tc in assistant_msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        # 3. Append the assistant message. Keep `tool_calls` populated even
        #    when final_answer is the only call — downstream readers (tests,
        #    the run loop's _is_terminal check) can still see the structure.
        state.messages.append(
            Message(
                role=Role.ASSISTANT,
                content=assistant_msg.content,
                tool_calls=tool_calls or None,
                finish_reason=choice.finish_reason,
                token_count=response.usage.total_tokens if response.usage else None,
            )
        )

        # 4. No tool calls → the assistant reply IS the final answer.
        if not tool_calls:
            return state

        # 5. final_answer short-circuit. We DON'T dispatch final_answer
        #    through the tool registry — instead, we treat its `answer`
        #    argument as the final assistant text and stop the loop. The
        #    final_answer tool itself is a *meta* signal, not a real tool.
        final_answer_call = self._extract_final_answer(tool_calls)
        if final_answer_call is not None:
            answer_text = self._final_answer_text(final_answer_call)
            # The prior assistant message still carries the tool_calls
            # field (we kept it for downstream readers). Mutate it in
            # place to drop the tool_calls so `_is_terminal()` doesn't
            # think there's pending work.
            prior = state.messages[-1]
            prior.tool_calls = None
            state.messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=answer_text,
                    finish_reason="stop",
                )
            )
            return state

        # 6. Otherwise dispatch every tool call and append a tool result
        #    message for each.
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

    # --- helpers exposed to subclasses (PlanAndSolve / Reflection) ------------

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

        if result.is_error:
            record_failure(tc.name)
        else:
            record_success(tc.name)

        # The LLM wants a string back. ToolResponse.ok data is `Any`; stringify nicely.
        content = result.content
        return ToolResult(
            tool_call_id=tc.id,
            content=content,
            is_error=result.is_error,
            truncated=bool(result.truncated),
        )

    @staticmethod
    def _extract_final_answer(tool_calls: list[ToolCall]) -> ToolCall | None:
        """Return the first `final_answer` tool_call, or None.

        Note: we check case-sensitively against `FINAL_ANSWER_TOOL` (lowercase).
        The LLM is told to use exactly that name in the system prompt.
        """
        for tc in tool_calls:
            if tc.name == FINAL_ANSWER_TOOL:
                return tc
        return None

    @staticmethod
    def _final_answer_text(tc: ToolCall) -> str:
        """Extract the final-answer text from a final_answer tool call's arguments.

        The argument is conventionally named `answer`, but we accept several
        common variants (`text`, `content`, `result`) for resilience.
        """
        args: dict[str, Any] = tc.arguments or {}
        for key in ("answer", "text", "content", "result", "final"):
            val = args.get(key)
            if isinstance(val, str) and val:
                return val
        # Fall back to a JSON dump of whatever was passed
        try:
            return json.dumps(args, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(args)

    # --- terminal-condition override -----------------------------------------

    def _is_terminal(self, state: AgentState) -> bool:
        """ReAct terminal: the chain has no pending tool calls.

        We treat the chain as terminal iff:
          - the last message is an ASSISTANT message with no tool_calls
            (the LLM has produced a final reply), OR
          - the conversation is empty.

        In all other cases (the last message is a TOOL or an ASSISTANT
        with tool_calls) there's still pending work.
        """
        if not state.messages:
            return True
        last = state.messages[-1]
        return last.role == Role.ASSISTANT and not last.tool_calls
