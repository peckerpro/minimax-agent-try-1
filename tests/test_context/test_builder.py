"""Tests for hello_agent.context.builder.ContextBuilder."""
from __future__ import annotations

import pytest

from hello_agent.context.builder import ContextBuilder, build_prompt
from hello_agent.core.types import AgentState, Message, Role


def _state(*msgs: Message) -> AgentState:
    return AgentState(session_id="sess-test", messages=list(msgs))


# --- construction ------------------------------------------------------------


def test_default_budget_honors_config() -> None:
    """Defaults come from `config.context.{max_context_tokens, response_reserve_tokens}`."""
    cb = ContextBuilder()
    # Spec defaults: 128_000 / 4_000.
    assert cb.max_context_tokens == 128_000
    assert cb.response_reserve_tokens == 4_000


def test_effective_prompt_tokens_excludes_reserve() -> None:
    cb = ContextBuilder(max_context_tokens=1000, response_reserve_tokens=200)
    assert cb.effective_prompt_tokens == 800


def test_invalid_budget_raises() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        ContextBuilder(max_context_tokens=0, response_reserve_tokens=0)
    with pytest.raises(ValueError, match="strictly less than"):
        ContextBuilder(max_context_tokens=100, response_reserve_tokens=200)


# --- build order -------------------------------------------------------------


def test_build_returns_system_then_history() -> None:
    """With no memory/rag chunks, the output is system + non-system history."""
    cb = ContextBuilder(max_context_tokens=10_000, response_reserve_tokens=1_000)
    state = _state(
        Message(role=Role.SYSTEM, content="be brief", system=True),
        Message(role=Role.USER, content="ping"),
        Message(role=Role.ASSISTANT, content="pong"),
    )
    out = cb.build(state)
    assert len(out) == 3
    assert out[0].role == Role.SYSTEM
    assert out[0].content == "be brief"
    # The leading system message in `state` is NOT duplicated.
    assert [m.content for m in out] == ["be brief", "ping", "pong"]


def test_build_injects_memory_chunks_before_history() -> None:
    cb = ContextBuilder(max_context_tokens=10_000, response_reserve_tokens=1_000)
    state = _state(
        Message(role=Role.SYSTEM, content="sys", system=True),
        Message(role=Role.USER, content="u"),
    )
    out = cb.build(state, memory_chunks=["user prefers terse answers"])
    assert out[0].content == "sys"
    assert out[1].content.startswith("[memory recall]")
    assert out[1].cache_breakpoint is True
    assert out[1].role == Role.SYSTEM
    assert out[2].content == "u"


def test_build_injects_rag_chunks_at_end() -> None:
    cb = ContextBuilder(max_context_tokens=10_000, response_reserve_tokens=1_000)
    state = _state(
        Message(role=Role.SYSTEM, content="sys", system=True),
        Message(role=Role.USER, content="u"),
    )
    out = cb.build(state, rag_chunks=["doc1", "doc2"])
    last = out[-1]
    assert last.role == Role.SYSTEM
    assert "[relevant documents]" in (last.content or "")
    assert "doc1" in (last.content or "")
    assert "doc2" in (last.content or "")


def test_build_inherits_system_prompt_from_state() -> None:
    """If `system_prompt` arg is None, the leading state SYSTEM message wins."""
    cb = ContextBuilder(max_context_tokens=10_000, response_reserve_tokens=1_000)
    state = _state(Message(role=Role.SYSTEM, content="from-state", system=True))
    out = cb.build(state)
    assert out[0].content == "from-state"


def test_build_with_explicit_system_prompt_overrides_state() -> None:
    cb = ContextBuilder(max_context_tokens=10_000, response_reserve_tokens=1_000)
    state = _state(Message(role=Role.SYSTEM, content="from-state", system=True))
    out = cb.build(state, system_prompt="from-arg")
    # The first system message should be from the arg; the state SYSTEM
    # is filtered out by the `role == SYSTEM` skip in the history loop.
    assert out[0].content == "from-arg"


# --- budget enforcement ------------------------------------------------------


def test_build_drops_oldest_messages_when_budget_exceeded() -> None:
    """A tiny budget must cause older non-system messages to be dropped."""
    cb = ContextBuilder(max_context_tokens=200, response_reserve_tokens=50)
    state = _state(
        Message(role=Role.SYSTEM, content="sys", system=True),
        *[
            Message(role=Role.USER, content=f"user-{i} " + "x" * 200)
            for i in range(20)
        ],
    )
    out = cb.build(state)
    # The system message must survive.
    assert out[0].role == Role.SYSTEM
    # Some user messages must have been dropped.
    assert len(out) < 21


def test_build_preserves_compressed_messages() -> None:
    """Compressed messages must NOT be dropped by the budget enforcer."""
    cb = ContextBuilder(max_context_tokens=300, response_reserve_tokens=50)
    state = _state(
        Message(role=Role.SYSTEM, content="sys", system=True),
        Message(role=Role.USER, content="compressed-digest", compressed=True),
        *[
            Message(role=Role.USER, content=f"u{i} " + "x" * 200)
            for i in range(10)
        ],
    )
    out = cb.build(state)
    contents = [m.content for m in out]
    assert any("compressed-digest" in (c or "") for c in contents)


# --- module-level convenience ------------------------------------------------


def test_module_build_prompt_equivalent_to_class() -> None:
    state = _state(
        Message(role=Role.SYSTEM, content="sys", system=True),
        Message(role=Role.USER, content="u"),
    )
    a = build_prompt(state)
    b = ContextBuilder().build(state)
    assert [m.content for m in a] == [m.content for m in b]


def test_build_does_not_mutate_state_messages() -> None:
    cb = ContextBuilder(max_context_tokens=10_000, response_reserve_tokens=1_000)
    state = _state(
        Message(role=Role.SYSTEM, content="sys", system=True),
        Message(role=Role.USER, content="u"),
    )
    original_len = len(state.messages)
    cb.build(state, memory_chunks=["m1"], rag_chunks=["r1"])
    assert len(state.messages) == original_len
