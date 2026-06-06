"""Tests for hello_agent.context.truncator."""
from __future__ import annotations

import pytest

from hello_agent.context.truncator import (
    ObservationTruncator,
    TruncatorStrategy,
    truncate,
)
from hello_agent.core.types import Message, Role

# --- construction ------------------------------------------------------------


def test_default_strategy_is_head_tail() -> None:
    """The Day-4 spec says `head_tail` is the default strategy."""
    t = ObservationTruncator()
    assert t.strategy == "head_tail"


def test_default_head_and_tail_lines() -> None:
    """The Day-4 config default is head=50, tail=20."""
    t = ObservationTruncator()
    assert t.head_lines == 50
    assert t.tail_lines == 20


def test_explicit_kwargs_override_defaults() -> None:
    t = ObservationTruncator(strategy="middle_out", head_lines=5, tail_lines=2)
    assert t.strategy == "middle_out"
    assert t.head_lines == 5
    assert t.tail_lines == 2


def test_head_and_tail_lines_must_be_positive() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        ObservationTruncator(head_lines=0)
    with pytest.raises(ValueError, match=">= 1"):
        ObservationTruncator(tail_lines=0)


# --- head_tail strategy ------------------------------------------------------


def test_head_tail_keeps_first_and_last_lines() -> None:
    body = "\n".join(f"line {i}" for i in range(100))
    src = Message(role=Role.TOOL, content=body, tool=True)
    t = ObservationTruncator(strategy="head_tail", head_lines=3, tail_lines=2)
    out = t.truncate(src, max_lines=5)
    lines = out.content.splitlines() if out.content else []
    assert lines[0] == "line 0"
    assert lines[1] == "line 1"
    assert lines[2] == "line 2"
    # The last two should be the tail.
    assert lines[-2] == "line 98"
    assert lines[-1] == "line 99"


def test_head_tail_inserts_truncation_marker() -> None:
    body = "\n".join(f"line {i}" for i in range(50))
    src = Message(role=Role.TOOL, content=body, tool=True)
    t = ObservationTruncator(strategy="head_tail", head_lines=5, tail_lines=5)
    out = t.truncate(src, max_lines=10)
    assert "lines truncated" in (out.content or "")


def test_truncate_returns_new_message_with_flag() -> None:
    body = "\n".join(f"line {i}" for i in range(100))
    src = Message(role=Role.TOOL, content=body, tool=True)
    t = ObservationTruncator(head_lines=5, tail_lines=5)
    out = t.truncate(src, max_lines=10)
    assert out is not src
    assert out.truncated is True
    # Original is untouched.
    assert src.truncated is False


def test_truncate_no_op_for_short_content() -> None:
    body = "a\nb\nc"
    src = Message(role=Role.TOOL, content=body, tool=True)
    t = ObservationTruncator(head_lines=5, tail_lines=5)
    out = t.truncate(src, max_lines=10)
    assert out is src
    assert out.truncated is False


def test_truncate_handles_none_content() -> None:
    """A message with no content is returned unchanged."""
    src = Message(role=Role.ASSISTANT, content=None)
    t = ObservationTruncator()
    out = t.truncate(src)
    assert out is src


# --- middle_out strategy -----------------------------------------------------


def test_middle_out_strategy_keeps_first_and_last() -> None:
    body = "\n".join(f"line {i}" for i in range(50))
    src = Message(role=Role.TOOL, content=body, tool=True)
    t = ObservationTruncator(strategy="middle_out", head_lines=5, tail_lines=5)
    out = t.truncate(src, max_lines=10)
    lines = out.content.splitlines() if out.content else []
    assert lines[0] == "line 0"
    assert lines[-1] == "line 49"
    assert "elided" in (out.content or "")


# --- summarize strategy (v0.1 falls back to head_tail) ---------------------


def test_summarize_strategy_falls_back_to_head_tail() -> None:
    body = "\n".join(f"line {i}" for i in range(50))
    src = Message(role=Role.TOOL, content=body, tool=True)
    t = ObservationTruncator(strategy="summarize", head_lines=3, tail_lines=3)
    out = t.truncate(src, max_lines=6)
    assert "lines truncated" in (out.content or "")


# --- module-level `truncate` shim --------------------------------------------


def test_module_truncate_shim_still_works() -> None:
    body = "\n".join(f"line {i}" for i in range(50))
    src = Message(role=Role.TOOL, content=body, tool=True)
    out = truncate(src, max_lines=10, strategy="head_tail", head_lines=3, tail_lines=3)
    assert out.truncated is True


# --- Type alias sanity -------------------------------------------------------


def test_truncator_strategy_literal_includes_all_options() -> None:
    """`TruncatorStrategy` exposes the three strategies from the spec."""
    # Statically check the literal.
    strategies: list[TruncatorStrategy] = ["head_tail", "middle_out", "summarize"]
    assert len(strategies) == 3
