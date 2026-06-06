"""Tests for hello_agent.context.token_counter."""
from __future__ import annotations

from hello_agent.context.token_counter import (
    _HEURISTIC_CHARS_PER_TOKEN,
    TokenCounter,
    count_text_tokens,
    count_tokens,
)
from hello_agent.core.types import Message, Role

# --- TokenCounter class ------------------------------------------------------


def test_counter_returns_positive_count_for_messages() -> None:
    """`count()` on a non-empty list must return > 0."""
    counter = TokenCounter(model="gpt-4o-mini")
    msgs = [
        Message(role=Role.SYSTEM, content="you are a helpful assistant"),
        Message(role=Role.USER, content="hello world"),
    ]
    assert counter.count(msgs) > 0


def test_counter_count_text_returns_positive() -> None:
    counter = TokenCounter(model="gpt-4o-mini")
    assert counter.count_text("hello world") >= 1


def test_counter_count_text_empty_returns_zero() -> None:
    counter = TokenCounter(model="gpt-4o-mini")
    assert counter.count_text("") == 0
    assert counter.count_text(None) == 0


def test_counter_count_text_heuristic_path() -> None:
    """With `use_tiktoken=False`, the counter uses chars/4."""
    counter = TokenCounter(use_tiktoken=False)
    assert counter.using_heuristic is True
    text = "a" * 40
    # 40 chars / 4 = 10 tokens
    assert counter.count_text(text) == 10


def test_counter_count_heuristic_4_chars_per_token() -> None:
    """Sanity: heuristic uses _HEURISTIC_CHARS_PER_TOKEN as the divisor."""
    counter = TokenCounter(use_tiktoken=False)
    text = "x" * (_HEURISTIC_CHARS_PER_TOKEN * 7)  # 28 chars
    assert counter.count_text(text) == 7


def test_counter_count_single_message() -> None:
    """`count(single_message)` must work (no wrapping in a list required)."""
    counter = TokenCounter()
    msg = Message(role=Role.USER, content="hi")
    assert counter.count(msg) >= 1


def test_counter_fits_helper() -> None:
    counter = TokenCounter(use_tiktoken=False)
    short = [Message(role=Role.USER, content="a" * 8)]  # 2 tokens
    assert counter.fits(short, budget=10) is True
    assert counter.fits(short, budget=1) is False


def test_counter_head_room_helper() -> None:
    counter = TokenCounter(use_tiktoken=False)
    # 4 overhead + 40/4 = 10 content tokens = 14 total
    msgs = [Message(role=Role.USER, content="a" * 40)]
    assert counter.count(msgs) == 14
    assert counter.head_room(msgs, budget=20) == 6
    assert counter.head_room(msgs, budget=14) == 0
    assert counter.head_room(msgs, budget=5) == -9


def test_counter_includes_tool_call_arguments() -> None:
    """Tool-call argument JSON should be counted (it's part of the prompt)."""
    counter = TokenCounter(use_tiktoken=False)
    from hello_agent.core.types import ToolCall

    msg = Message(
        role=Role.ASSISTANT,
        content=None,
        tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "abcdefghij"})],
    )
    # 4 overhead + 0 (no content) + "echo" (1 token at chars/4) + str(args) (5 tokens at chars/4)
    # str({"text": "abcdefghij"}) = "{'text': 'abcdefghij'}" = 23 chars → 5 tokens (23//4)
    # total: 4 + 1 + 5 = 10
    assert counter.count(msg) == 10


# --- module-level helpers ----------------------------------------------------


def test_module_count_tokens_matches_class() -> None:
    """`count_tokens(msgs)` should agree with `TokenCounter().count(msgs)`."""
    msgs = [
        Message(role=Role.SYSTEM, content="be brief"),
        Message(role=Role.USER, content="hi"),
    ]
    assert count_tokens(msgs, model="gpt-4o-mini") == TokenCounter(model="gpt-4o-mini").count(msgs)


def test_module_count_text_tokens_returns_zero_for_empty() -> None:
    assert count_text_tokens("") == 0
    assert count_text_tokens(None) == 0  # type: ignore[arg-type]


def test_module_count_text_tokens_returns_positive() -> None:
    assert count_text_tokens("hello world") >= 1
