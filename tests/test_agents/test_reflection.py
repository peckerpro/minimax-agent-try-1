"""Tests for hello_agent.agents.reflection.ReflectionAgent.

The agent is exercised against a mocked LLMClient. We verify:
  - One round of execution (no issues) terminates.
  - Reflection triggers a second round when the reviewer says "revise".
  - max_reflection_rounds caps the loop.
  - A failed reflection call is treated as "accept" (graceful).
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from hello_agent.agents.reflection import ReflectionAgent
from hello_agent.core.types import (
    ToolDefinition,
    ToolResult,
)
from hello_agent.tools.registry import ToolRegistry

# --- helpers ----------------------------------------------------------------


class _StubChoice:
    def __init__(self, content: str | None) -> None:
        self.message = MagicMock()
        self.message.content = content
        self.message.tool_calls = None
        self.finish_reason = "stop"


class _StubResponse:
    def __init__(self, content: str | None = None, usage: Any = None) -> None:
        self.choices = [_StubChoice(content)]
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


def _ok_verdict() -> _StubResponse:
    return _StubResponse(content=json.dumps({"verdict": "ok"}))


def _revise_verdict(critique: str = "missing citations") -> _StubResponse:
    return _StubResponse(content=json.dumps({"verdict": "revise", "critique": critique}))


def _text_response(text: str) -> _StubResponse:
    return _StubResponse(content=text)


# --- core tests -------------------------------------------------------------


def test_reflection_accepts_first_answer() -> None:
    """One execution + one reflection round (verdict=ok) → done in 2 LLM calls."""
    llm = MagicMock()
    llm.chat.side_effect = [
        _text_response("here is the answer"),
        _ok_verdict(),
    ]
    agent = ReflectionAgent(llm=llm, tool_registry=_make_registry())
    state = agent.run("what is 2 + 2?")

    # 1 execution + 1 reflection = 2 LLM calls.
    assert llm.chat.call_count == 2
    # state.reflection_rounds is set.
    rounds = getattr(state, "reflection_rounds", None)
    assert rounds is not None
    assert len(rounds) == 1
    assert rounds[0]["verdict"] == "ok"


def test_reflection_iterates_on_revise() -> None:
    """verdict=revise triggers a second round; 2 rounds = 3 LLM calls (exec, reflect, exec)."""
    llm = MagicMock()
    llm.chat.side_effect = [
        _text_response("first draft answer"),
        _revise_verdict("please add a closing paragraph"),
        _text_response("revised answer"),
        _ok_verdict(),
    ]
    agent = ReflectionAgent(llm=llm, tool_registry=_make_registry(), max_reflection_rounds=3)
    state = agent.run("write a short bio")

    # 2 executions + 2 reflections = 4 LLM calls.
    assert llm.chat.call_count == 4
    rounds = getattr(state, "reflection_rounds", None)
    assert rounds is not None
    assert len(rounds) == 2
    assert rounds[0]["verdict"] == "revise"
    assert rounds[1]["verdict"] == "ok"


def test_reflection_respects_max_rounds_cap() -> None:
    """If the reviewer keeps saying 'revise', the agent stops after max_reflection_rounds."""
    llm = MagicMock()
    llm.chat.side_effect = [
        # Round 1: exec + revise
        _text_response("v1"),
        _revise_verdict("try again"),
        # Round 2: exec + revise
        _text_response("v2"),
        _revise_verdict("try again"),
        # Round 3: exec + revise (CAPPED — we won't run another reflection)
        _text_response("v3"),
    ]
    agent = ReflectionAgent(llm=llm, tool_registry=_make_registry(), max_reflection_rounds=2)
    state = agent.run("keep iterating")

    # max_reflection_rounds=2 → 2 executions + 2 reflections = 4 calls.
    # The "v3" reply never happens because the cap hits.
    assert llm.chat.call_count == 4
    rounds = getattr(state, "reflection_rounds", None)
    assert rounds is not None
    assert len(rounds) == 2


def test_reflection_handles_empty_reply_gracefully() -> None:
    """If the LLM produces an empty final text, reflection treats it as 'ok' (no review)."""
    llm = MagicMock()
    llm.chat.side_effect = [
        _text_response(""),
        # The reflection call shouldn't even happen because _last_assistant_text returns ""
        # and we treat empty replies as accept.
    ]
    agent = ReflectionAgent(llm=llm, tool_registry=_make_registry())
    state = agent.run("anything")

    # 1 LLM call (the execution); no reflection because the reply was empty.
    assert llm.chat.call_count == 1
    rounds = getattr(state, "reflection_rounds", None)
    assert rounds is not None and len(rounds) == 1
    assert rounds[0]["verdict"] == "ok"


def test_reflection_handles_reflection_call_failure() -> None:
    """If the reflection call itself raises, the agent accepts the current result."""
    llm = MagicMock()
    llm.chat.side_effect = [
        _text_response("first answer"),
        RuntimeError("reviewer unavailable"),
    ]
    agent = ReflectionAgent(llm=llm, tool_registry=_make_registry())
    state = agent.run("anything")
    # 1 execution + 1 failed reflection (caught).
    assert llm.chat.call_count == 2
    rounds = getattr(state, "reflection_rounds", None)
    assert rounds is not None and len(rounds) == 1
    assert rounds[0]["verdict"] == "ok"


def test_reflection_parses_loose_verdict() -> None:
    """Loose phrases like 'looks good' or 'revise' are accepted."""
    llm = MagicMock()
    llm.chat.side_effect = [
        _text_response("first answer"),
        _StubResponse(content="Looks good to me!"),
    ]
    agent = ReflectionAgent(llm=llm, tool_registry=_make_registry())
    state = agent.run("anything")
    rounds = getattr(state, "reflection_rounds", None)
    assert rounds is not None and rounds[0]["verdict"] == "ok"


def test_reflection_parses_revise_prose() -> None:
    """Prose containing 'revise' / 'missing' is treated as revise."""
    llm = MagicMock()
    llm.chat.side_effect = [
        _text_response("first answer"),
        _StubResponse(content="The answer is missing examples. Please revise."),
        _text_response("second answer with examples"),
        _ok_verdict(),
    ]
    agent = ReflectionAgent(llm=llm, tool_registry=_make_registry(), max_reflection_rounds=3)
    state = agent.run("anything")
    assert llm.chat.call_count == 4
    rounds = getattr(state, "reflection_rounds", None)
    assert rounds is not None and len(rounds) == 2
    assert rounds[0]["verdict"] == "revise"


def test_reflection_rejects_invalid_max_rounds() -> None:
    """max_reflection_rounds must be >= 1."""
    with pytest.raises(ValueError, match="max_reflection_rounds"):
        ReflectionAgent(
            llm=MagicMock(),
            tool_registry=_make_registry(),
            max_reflection_rounds=0,
        )


def test_reflection_session_id_propagates() -> None:
    """session_id from the constructor flows into the returned AgentState."""
    llm = MagicMock()
    llm.chat.side_effect = [_text_response("ok"), _ok_verdict()]
    agent = ReflectionAgent(llm=llm, tool_registry=_make_registry(), session_id="sess-X")
    state = agent.run("anything")
    assert state.session_id == "sess-X"
