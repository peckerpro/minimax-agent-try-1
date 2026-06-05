"""Tests for hello_agent.agents.plan_solve.PlanAndSolveAgent.

The agent is exercised against a mocked LLMClient so we don't need a real
API key. The mock LLM is set up to:
  1. First, return a JSON plan (the planning call)
  2. Then, return one or more tool-call / text replies per sub-step
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from hello_agent.agents.plan_solve import PlanAndSolveAgent
from hello_agent.core.types import (
    Role,
    ToolDefinition,
    ToolResult,
)
from hello_agent.tools.registry import ToolRegistry

# --- helpers ----------------------------------------------------------------


class _StubToolCall:
    def __init__(self, name: str, arguments: str, call_id: str) -> None:
        self.id = call_id
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = arguments


class _StubMessage:
    def __init__(self, content: str | None = None, tool_calls: list[_StubToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class _StubChoice:
    def __init__(self, content: str | None, tool_calls: list[_StubToolCall] | None, finish_reason: str = "stop") -> None:
        self.message = _StubMessage(content=content, tool_calls=tool_calls)
        self.finish_reason = finish_reason


class _StubResponse:
    def __init__(self, content: str | None = None, tool_calls: list[_StubToolCall] | None = None, usage: Any = None) -> None:
        self.choices = [_StubChoice(content=content, tool_calls=tool_calls, finish_reason="stop")]
        self.usage = usage


def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        name="echo",
        toolset="smoke",
        schema=ToolDefinition(
            name="echo",
            description="echoes input",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        ),
        handler=lambda args, **kw: ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=f"echo:{args.get('text', '')}",
        ),
    )
    return reg


def _plan_response(steps: list[dict]) -> _StubResponse:
    return _StubResponse(content=json.dumps(steps))


def _text_response(text: str) -> _StubResponse:
    return _StubResponse(content=text)


def _tool_call(name: str, args: dict, call_id: str = "call-1") -> _StubResponse:
    return _StubResponse(
        tool_calls=[_StubToolCall(name=name, arguments=json.dumps(args), call_id=call_id)]
    )


# --- core tests -------------------------------------------------------------


def test_plan_solve_runs_all_steps() -> None:
    """Planning returns 3 steps; agent must invoke the LLM 1 + 3*N times (plan + per-step)."""
    llm = MagicMock()
    plan = [
        {"step": 1, "description": "List the files"},
        {"step": 2, "description": "Filter by size"},
        {"step": 3, "description": "Summarize"},
    ]
    # Plan call returns JSON. Per-step calls return a text reply each.
    llm.chat.side_effect = [
        _plan_response(plan),
        _text_response("file list ready"),
        _text_response("filtered"),
        _text_response("summary done"),
    ]
    agent = PlanAndSolveAgent(llm=llm, tool_registry=_make_registry(), max_iterations=50)
    state = agent.run("organize my downloads")

    # 1 plan call + 3 sub-step calls = 4 LLM calls.
    assert llm.chat.call_count == 4
    # The plan is stashed on the state for downstream consumers.
    assert getattr(state, "plan", None) == plan
    # Last user message in state should reflect the final sub-step result.
    last_user_msgs = [m for m in state.messages if m.role == Role.USER]
    assert any("summary done" in (m.content or "") for m in last_user_msgs)


def test_plan_solve_handles_malformed_plan() -> None:
    """A garbage plan reply falls back to a single-step run."""
    llm = MagicMock()
    llm.chat.side_effect = [
        _StubResponse(content="not even JSON, just prose"),
        _text_response("ok"),
    ]
    agent = PlanAndSolveAgent(llm=llm, tool_registry=_make_registry())
    state = agent.run("anything")
    # 1 plan + 1 sub-step.
    assert llm.chat.call_count == 2
    # The fallback plan is a single step with the user message as the description.
    plan = getattr(state, "plan", None)
    assert plan is not None and len(plan) == 1
    assert plan[0]["description"] == "anything"


def test_plan_solve_handles_plan_call_exception() -> None:
    """If the plan call itself raises, we fall back to a single-step run."""
    llm = MagicMock()
    llm.chat.side_effect = [
        RuntimeError("provider 500"),
        _text_response("ok"),
    ]
    agent = PlanAndSolveAgent(llm=llm, tool_registry=_make_registry())
    state = agent.run("anything")
    # Plan call raises → fallback to 1 sub-step. The sub-step runs to terminal
    # with the text response. So: 1 plan call (raised, no LLM round-trip counted
    # as success) + 1 sub-step call = 2 recorded calls (the raise still counts).
    assert llm.chat.call_count == 2
    plan = getattr(state, "plan", None)
    assert plan is not None and len(plan) == 1


def test_plan_solve_parses_bulleted_plan() -> None:
    """A bullet-list reply is parsed as a plan when the JSON parser fails."""
    llm = MagicMock()
    # 1 plan call (with bullet text) + 3 sub-step text replies.
    llm.chat.side_effect = [
        _StubResponse(content="- First, list the files\n- Then, summarize\n- Finally, report"),
        _text_response("ok 1"),
        _text_response("ok 2"),
        _text_response("ok 3"),
    ]
    agent = PlanAndSolveAgent(llm=llm, tool_registry=_make_registry())
    state = agent.run("anything")
    plan = getattr(state, "plan", None)
    assert plan is not None and len(plan) == 3
    assert plan[0]["description"].startswith("First, list")
    assert plan[2]["description"].startswith("Finally")
    # 1 plan + 3 sub-step calls.
    assert llm.chat.call_count == 4


def test_plan_solve_handles_tool_calls_in_substep() -> None:
    """A sub-step can issue a tool call before finishing."""
    llm = MagicMock()
    plan = [{"step": 1, "description": "echo something"}]
    llm.chat.side_effect = [
        _plan_response(plan),
        _tool_call("echo", {"text": "hi"}),
        _text_response("done"),
    ]
    agent = PlanAndSolveAgent(llm=llm, tool_registry=_make_registry(), max_iterations=20)
    state = agent.run("ping")
    assert llm.chat.call_count == 3
    # The echo tool was actually invoked — check on the exposed sub_states,
    # not the parent state (parent only sees a high-level result message).
    sub_states = getattr(state, "sub_states", None)
    assert sub_states is not None and len(sub_states) == 1
    tool_msgs = [m for m in sub_states[0].messages if m.role == Role.TOOL]
    assert any(m.tool_name == "echo" and m.content == "echo:hi" for m in tool_msgs)


def test_plan_solve_respects_max_iterations() -> None:
    """If the LLM keeps making tool calls within a sub-step, the sub-step loop caps."""
    llm = MagicMock()
    plan = [{"step": 1, "description": "do something"}]
    # Plan + 5 tool calls (no final answer) — should cap at 5 sub-iterations.
    llm.chat.side_effect = [
        _plan_response(plan),
        # Sub-step: 5 identical tool calls, then a text reply.
        _tool_call("echo", {"text": "1"}),
        _tool_call("echo", {"text": "2"}),
        _tool_call("echo", {"text": "3"}),
        _tool_call("echo", {"text": "4"}),
        _tool_call("echo", {"text": "5"}),
        _text_response("done"),
    ]
    agent = PlanAndSolveAgent(llm=llm, tool_registry=_make_registry(), max_iterations=8)
    agent.run("anything")
    # 1 plan + 5 tool calls + 1 text = 7 LLM calls. Sub-step capped at
    # max(2, 8 // 4) = 2 iterations, so only 2 tool calls happen.
    # Actually let me re-check the math: max_iterations // 4 = 2.
    # Sub-step runs: iteration 1 = tool call, iteration 2 = tool call, then
    # max_iterations hit. So 1 plan + 2 sub-step calls = 3 LLM calls.
    assert llm.chat.call_count == 3
