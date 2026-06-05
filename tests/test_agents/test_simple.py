"""Tests for hello_agent.agents.simple.SimpleAgent.

The agent is exercised against a mocked LLMClient so we don't need a real
API key to run these tests.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from hello_agent.agents.simple import SimpleAgent
from hello_agent.core.types import AgentState, Role


class _StubChoice:
    """Mimics an openai.types.chat.chat_completion.Choice for the agent."""

    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.message = MagicMock()
        self.message.content = content
        self.message.tool_calls = None
        self.finish_reason = finish_reason


class _StubResponse:
    def __init__(self, content: str, finish_reason: str = "stop", usage: Any = None) -> None:
        self.choices = [_StubChoice(content, finish_reason)]
        self.usage = usage


@pytest.fixture()
def mock_llm() -> MagicMock:
    """A MagicMock that satisfies the LLMClient.chat() shape used by SimpleAgent."""
    llm = MagicMock()
    llm.chat.return_value = _StubResponse("hello from the mock")
    return llm


def test_simple_agent_returns_mock_text(mock_llm: MagicMock) -> None:
    """SimpleAgent must surface the LLM's text reply as the final message."""
    agent = SimpleAgent(llm=mock_llm, system_prompt="be brief")
    state = agent.run("ping")

    # The agent must have appended an assistant message to the state.
    assert state.messages, "state.messages is empty after run()"
    last = state.messages[-1]
    assert last.role == Role.ASSISTANT
    assert last.content == "hello from the mock"
    assert last.finish_reason == "stop"

    # And the LLMClient.chat() was called with at least the system + user message.
    mock_llm.chat.assert_called_once()
    kwargs = mock_llm.chat.call_args.kwargs
    messages = kwargs.get("messages") or mock_llm.chat.call_args.args[0]
    roles = [m.role for m in messages]
    assert Role.SYSTEM in roles
    assert Role.USER in roles


def test_simple_agent_propagates_llm_exceptions(mock_llm: MagicMock) -> None:
    """SimpleAgent must surface LLMClient.chat() errors to the caller (no swallowing)."""
    mock_llm.chat.side_effect = RuntimeError("provider unavailable")
    agent = SimpleAgent(llm=mock_llm)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        agent.run("ping")


def test_simple_agent_records_finish_reason(mock_llm: MagicMock) -> None:
    """The finish_reason from the LLM response is preserved on the final message."""
    mock_llm.chat.return_value = _StubResponse("ok", finish_reason="length")
    agent = SimpleAgent(llm=mock_llm)

    state = agent.run("hi")
    assert state.messages[-1].finish_reason == "length"


def test_simple_agent_session_id_is_stable(mock_llm: MagicMock) -> None:
    """Reusing a session_id across two agents keeps them in the same session."""
    a = SimpleAgent(llm=mock_llm, system_prompt="x", session_id="fixed-id")
    b = SimpleAgent(llm=mock_llm, system_prompt="x", session_id="fixed-id")
    assert a.session_id == b.session_id == "fixed-id"


def test_simple_agent_no_tools(mock_llm: MagicMock) -> None:
    """SimpleAgent must never pass tools= to the LLM (it has no tool registry)."""
    agent = SimpleAgent(llm=mock_llm)
    agent.run("ping")

    kwargs = mock_llm.chat.call_args.kwargs
    tools = kwargs.get("tools")
    # Either absent or explicitly None — SimpleAgent never sends tools.
    assert tools in (None,)


def test_simple_agent_state_has_session_id(mock_llm: MagicMock) -> None:
    """The AgentState returned by run() must carry the agent's session_id."""
    agent = SimpleAgent(llm=mock_llm, session_id="sess-1")
    state: AgentState = agent.run("ping")
    assert state.session_id == "sess-1"
