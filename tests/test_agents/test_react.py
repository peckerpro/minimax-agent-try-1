"""Tests for hello_agent.agents.react.ReActAgent.

The agent is exercised against a mocked LLMClient so we don't need a real
API key to run these tests.

Key scenarios covered (per day-3 spec):
  - ReAct loop terminates when the LLM emits a tool_call then a final
    plain-text reply.
  - `final_answer` tool-call short-circuits the loop without dispatching
    the registered `final_answer` tool.
  - The loop respects `max_iterations` when the LLM keeps emitting
    tool_calls forever.
  - The LLM is always called with the agent's tool schemas (never `None`).
  - Permission-denied tools don't crash the loop.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from hello_agent.agents.react import FINAL_ANSWER_TOOL, ReActAgent
from hello_agent.core.types import (
    AgentState,
    Role,
    ToolDefinition,
    ToolResult,
)
from hello_agent.tools.registry import ToolRegistry

# --- helpers ----------------------------------------------------------------


class _StubToolCall:
    """Mimics `openai.types.chat.chat_completion_message_tool_call.Function`."""

    def __init__(self, name: str, arguments: str, call_id: str) -> None:
        self.id = call_id
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = arguments


class _StubMessage:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[_StubToolCall] | None = None,
    ) -> None:
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


def _final_answer_response(answer: str) -> _StubResponse:
    """A response where the LLM emits a `final_answer` tool_call."""
    return _StubResponse(
        tool_calls=[
            _StubToolCall(
                name=FINAL_ANSWER_TOOL,
                arguments=json.dumps({"answer": answer}),
                call_id="call-final-1",
            )
        ]
    )


def _tool_call_response(name: str, args: dict, call_id: str = "call-1") -> _StubResponse:
    """A response where the LLM emits a single non-final tool call."""
    return _StubResponse(
        tool_calls=[
            _StubToolCall(
                name=name,
                arguments=json.dumps(args),
                call_id=call_id,
            )
        ]
    )


def _text_response(content: str) -> _StubResponse:
    """A plain text reply (no tool calls)."""
    return _StubResponse(content=content)


def _make_tool_registry() -> ToolRegistry:
    """Build a tiny registry with a fake `final_answer` and an `echo` tool."""
    reg = ToolRegistry()

    reg.register(
        name=FINAL_ANSWER_TOOL,
        toolset="smoke",
        schema=ToolDefinition(
            name=FINAL_ANSWER_TOOL,
            description="Submit the final answer to the user.",
            parameters={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        ),
        handler=lambda args, **kw: ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=str(args.get("answer", "")),
        ),
    )
    reg.register(
        name="echo",
        toolset="smoke",
        schema=ToolDefinition(
            name="echo",
            description="Echoes the input back.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        handler=lambda args, **kw: ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=f"echo:{args.get('text', '')}",
        ),
    )
    return reg


# --- the day-3 core test: tool_call then final_answer → 2 iterations -------


def test_react_loop_terminates_after_tool_call_then_final_answer() -> None:
    """The headline day-3 test: LLM emits a tool_call, then a final_answer
    tool_call. ReActAgent must terminate after exactly 2 iterations, with
    the final answer promoted to an assistant message and no extra
    dispatching.
    """
    llm = MagicMock()
    llm.chat.side_effect = [
        _tool_call_response("echo", {"text": "hi"}),
        _final_answer_response("the answer is 42"),
    ]
    agent = ReActAgent(llm=llm, tool_registry=_make_tool_registry())

    state = agent.run("ask me anything")

    # Two LLM calls → exactly 2 iterations.
    assert state.iteration == 2
    assert llm.chat.call_count == 2

    # The conversation ends with the promoted final answer.
    last = state.messages[-1]
    assert last.role == Role.ASSISTANT
    assert last.content == "the answer is 42"
    assert last.tool_calls is None  # promoted, no tool_calls attached

    # The echo tool was actually dispatched (it's NOT final_answer).
    tool_msgs = [m for m in state.messages if m.role == Role.TOOL]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_name == "echo"
    assert tool_msgs[0].content == "echo:hi"

    # The final_answer tool_call appears in an earlier assistant message
    # but the agent did NOT append a TOOL message for it (short-circuit).
    final_answer_tool_msgs = [m for m in tool_msgs if m.tool_name == FINAL_ANSWER_TOOL]
    assert final_answer_tool_msgs == []


def test_react_loop_terminates_on_plain_text_reply() -> None:
    """No tool calls at all → loop terminates after 1 iteration."""
    llm = MagicMock()
    llm.chat.return_value = _text_response("just a plain reply")
    agent = ReActAgent(llm=llm, tool_registry=_make_tool_registry())

    state = agent.run("hi")

    assert state.iteration == 1
    assert llm.chat.call_count == 1
    last = state.messages[-1]
    assert last.role == Role.ASSISTANT
    assert last.content == "just a plain reply"


def test_react_loop_respects_max_iterations() -> None:
    """When the LLM never returns a non-tool-call reply, the loop caps at max_iterations."""
    llm = MagicMock()
    # Always emit an echo tool call.
    llm.chat.return_value = _tool_call_response("echo", {"text": "loop"})
    agent = ReActAgent(llm=llm, tool_registry=_make_tool_registry(), max_iterations=4)

    state = agent.run("do something")

    assert state.iteration == 4
    # We expect 4 LLM calls (one per step in the run loop).
    assert llm.chat.call_count == 4


def test_react_loop_passes_tool_schemas_to_llm() -> None:
    """Every LLM call gets a non-empty `tools` argument from the registry."""
    llm = MagicMock()
    llm.chat.side_effect = [
        _tool_call_response("echo", {"text": "x"}),
        _text_response("done"),
    ]
    agent = ReActAgent(llm=llm, tool_registry=_make_tool_registry())

    agent.run("hi")

    for call in llm.chat.call_args_list:
        tools = call.kwargs.get("tools")
        # Tool schemas must be passed (a non-empty list).
        assert tools is not None
        names = {t.name for t in tools}
        assert {"echo", FINAL_ANSWER_TOOL} <= names


def test_react_loop_handles_tool_execution_error_gracefully() -> None:
    """If a tool call fails (handler raises), the loop continues with the error stringified."""
    llm = MagicMock()
    reg = _make_tool_registry()

    # Replace `echo` with one that raises
    def _boom(args, **kw):  # noqa: ARG001
        raise RuntimeError("simulated failure")

    reg.register(
        name="boom",
        toolset="smoke",
        schema=ToolDefinition(
            name="boom",
            description="always fails",
            parameters={"type": "object", "properties": {}},
        ),
        handler=_boom,
    )

    llm.chat.side_effect = [
        _tool_call_response("boom", {}, call_id="call-boom-1"),
        _text_response("ok, recovered"),
    ]
    agent = ReActAgent(llm=llm, tool_registry=reg, max_iterations=5)
    state = agent.run("test")

    # Two iterations: one tool call (error), one final reply.
    assert state.iteration == 2
    # The tool message should be marked as error.
    tool_msgs = [m for m in state.messages if m.role == Role.TOOL]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_name == "boom"
    assert "simulated failure" in tool_msgs[0].content


def test_react_final_answer_with_text_field_fallback() -> None:
    """`final_answer` accepts `text` as well as `answer`."""
    llm = MagicMock()
    llm.chat.return_value = _StubResponse(
        tool_calls=[
            _StubToolCall(
                name=FINAL_ANSWER_TOOL,
                arguments=json.dumps({"text": "the text-field answer"}),
                call_id="call-1",
            )
        ]
    )
    agent = ReActAgent(llm=llm, tool_registry=_make_tool_registry())
    state = agent.run("go")
    assert state.iteration == 1
    last = state.messages[-1]
    assert last.role == Role.ASSISTANT
    assert last.content == "the text-field answer"


def test_react_session_id_passthrough() -> None:
    """`session_id` flows through to the AgentState."""
    llm = MagicMock()
    llm.chat.return_value = _text_response("ok")
    agent = ReActAgent(
        llm=llm,
        tool_registry=_make_tool_registry(),
        session_id="my-session",
    )
    state: AgentState = agent.run("hi")
    assert state.session_id == "my-session"


def test_react_final_answer_no_other_tools_dispatched() -> None:
    """When the LLM emits final_answer alongside another tool, NEITHER gets dispatched."""
    llm = MagicMock()
    llm.chat.return_value = _StubResponse(
        tool_calls=[
            _StubToolCall(
                name=FINAL_ANSWER_TOOL,
                arguments=json.dumps({"answer": "done"}),
                call_id="call-final",
            ),
            _StubToolCall(
                name="echo",
                arguments=json.dumps({"text": "should-not-run"}),
                call_id="call-echo",
            ),
        ]
    )
    agent = ReActAgent(llm=llm, tool_registry=_make_tool_registry())
    state = agent.run("multi")
    assert state.iteration == 1
    # No TOOL messages at all — the final_answer short-circuits the dispatch loop.
    tool_msgs = [m for m in state.messages if m.role == Role.TOOL]
    assert tool_msgs == []
    # The final answer is promoted as an assistant message.
    last = state.messages[-1]
    assert last.role == Role.ASSISTANT
    assert last.content == "done"


def test_react_state_iteration_reflects_loop_count() -> None:
    """`state.iteration` equals the number of LLM calls made (i.e. the loop count)."""
    llm = MagicMock()
    llm.chat.side_effect = [
        _tool_call_response("echo", {"text": "1"}),
        _tool_call_response("echo", {"text": "2"}),
        _text_response("done"),
    ]
    agent = ReActAgent(llm=llm, tool_registry=_make_tool_registry(), max_iterations=10)
    state = agent.run("test")
    assert state.iteration == 3
