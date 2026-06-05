"""Observation truncator — compress long tool output before feeding it to the LLM.

Strategies:
- head_tail: keep first N lines, last M lines, mark the middle as truncated.
- middle_out: keep first N + last M, replace the middle with a brief summary line.
- summarize:  reserved for v0.3+ (would call an LLM).
"""
from __future__ import annotations

from typing import Literal

from hello_agent.core.types import Message

TruncatorStrategy = Literal["head_tail", "middle_out", "summarize"]


def _split_lines(text: str) -> list[str]:
    return text.splitlines()


def _join_lines(lines: list[str]) -> str:
    return "\n".join(lines)


def truncate(
    message: Message,
    max_lines: int = 70,
    strategy: TruncatorStrategy = "head_tail",
    head_lines: int | None = None,
    tail_lines: int | None = None,
) -> Message:
    """Return a copy of `message` whose `content` is truncated per the chosen strategy.

    If the message has no string content, returns it unchanged.
    """
    if message.content is None:
        return message

    head_n = head_lines if head_lines is not None else max(1, max_lines - 20)
    tail_n = tail_lines if tail_lines is not None else max(1, max_lines - head_n)

    lines = _split_lines(message.content)
    if len(lines) <= max_lines:
        return message

    if strategy == "head_tail":
        head = lines[:head_n]
        tail = lines[-tail_n:] if tail_n else []
        truncated_text = _join_lines(
            head + [f"\n[... {len(lines) - head_n - tail_n} lines truncated ...]\n"] + tail
        )
    elif strategy == "middle_out":
        head = lines[: max(1, max_lines // 2)]
        tail = lines[-max(1, max_lines // 2) :]
        truncated_text = _join_lines(
            head + [f"\n[... {len(lines) - len(head) - len(tail)} lines elided ...]\n"] + tail
        )
    elif strategy == "summarize":
        # v0.1: fall back to head_tail. v0.3+ will call an LLM here.
        return truncate(message, max_lines=max_lines, strategy="head_tail",
                        head_lines=head_n, tail_lines=tail_n)
    else:
        raise ValueError(f"Unknown truncator strategy: {strategy}")

    return Message(
        role=message.role,
        content=truncated_text,
        tool_calls=message.tool_calls,
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        name=message.name,
        timestamp=message.timestamp,
        token_count=message.token_count,
        finish_reason=message.finish_reason,
        reasoning=message.reasoning,
        cache_breakpoint=message.cache_breakpoint,
    )
