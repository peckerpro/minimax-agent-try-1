"""Observation truncator — compress long tool output before feeding it to the LLM.

Strategies (Day-4 spec, ENGINEERING.md §6.5):

- `head_tail`   keep first N + last M lines, mark the middle as truncated
                (this is the default and the only one the smoke test exercises)
- `middle_out`  keep first N + last M, replace the middle with an elision marker
                (functionally similar to head_tail but the marker is shorter)
- `summarize`   v0.1 falls back to head_tail; v0.3+ will call an LLM

Public API:

- `ObservationTruncator(strategy=..., head_lines=..., tail_lines=...)` —
  configurable class. The strategy/head/tail defaults come from
  `config.context.truncator_strategy`, `truncator_head_lines`, `truncator_tail_lines`
  (Day-4 spec: see §4.3 config.yaml `context.truncator`).
- `truncate(message, max_lines=...) -> Message` — module-level helper kept
  for back-compat with code that pre-dates the class.

`ObservationTruncator` always returns a *new* `Message` with
`truncated=True` set on the copy. The original message is left untouched.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from hello_agent.core.types import Message

if TYPE_CHECKING:
    from hello_agent.core.config import HelloAgentConfig

TruncatorStrategy = Literal["head_tail", "middle_out", "summarize"]

_STRATEGY_HEAD_TAIL = "head_tail"
_STRATEGY_MIDDLE_OUT = "middle_out"
_STRATEGY_SUMMARIZE = "summarize"

_DEFAULT_STRATEGY: TruncatorStrategy = _STRATEGY_HEAD_TAIL
_DEFAULT_HEAD_LINES = 50
_DEFAULT_TAIL_LINES = 20


def _strategy_from_config() -> tuple[TruncatorStrategy, int, int]:
    """Read truncator settings from `config.context`; fall back to defaults.

    Deferred import keeps this module cheap to import for callers that don't
    need config (e.g. unit tests using literal kwargs).
    """
    try:
        from hello_agent.core.config import get_config

        cfg: HelloAgentConfig = get_config()
        ctx = cfg.context
        strategy = ctx.truncator_strategy or _DEFAULT_STRATEGY
        head = int(ctx.truncator_head_lines) or _DEFAULT_HEAD_LINES
        tail = int(ctx.truncator_tail_lines) or _DEFAULT_TAIL_LINES
        return strategy, head, tail
    except Exception:  # noqa: BLE001
        return _DEFAULT_STRATEGY, _DEFAULT_HEAD_LINES, _DEFAULT_TAIL_LINES


def _split_lines(text: str) -> list[str]:
    return text.splitlines()


def _join_lines(lines: list[str]) -> str:
    return "\n".join(lines)


def _head_tail_truncate(
    lines: list[str], head_n: int, tail_n: int
) -> tuple[list[str], int]:
    """Keep first `head_n` and last `tail_n` lines; mark the middle truncated.

    Returns (new_lines, dropped_count).
    """
    if head_n + tail_n >= len(lines):
        return lines[:], 0
    head = lines[:head_n]
    tail = lines[-tail_n:] if tail_n else []
    dropped = len(lines) - head_n - tail_n
    marker = [f"\n[... {dropped} lines truncated ...]\n"]
    return head + marker + tail, dropped


def _middle_out_truncate(lines: list[str], max_lines: int) -> tuple[list[str], int]:
    """Keep first half + last half of `max_lines`; mark the middle elided."""
    if max_lines >= len(lines):
        return lines[:], 0
    half = max(1, max_lines // 2)
    head = lines[:half]
    tail = lines[-half:]
    dropped = len(lines) - len(head) - len(tail)
    marker = [f"\n[... {dropped} lines elided ...]\n"]
    return head + marker + tail, dropped


def truncate(
    message: Message,
    max_lines: int = 70,
    strategy: TruncatorStrategy = _DEFAULT_STRATEGY,
    head_lines: int | None = None,
    tail_lines: int | None = None,
) -> Message:
    """Return a *new* `Message` whose `content` is truncated per `strategy`.

    If the message has no string content, returns it unchanged.
    Back-compat shim — most callers should use `ObservationTruncator`.
    """
    return ObservationTruncator(
        strategy=strategy,
        head_lines=head_lines,
        tail_lines=tail_lines,
    ).truncate(message, max_lines=max_lines)


class ObservationTruncator:
    """Configurable truncator for long tool observations.

    Reads its defaults from `config.context.truncator.*` (see
    `config.yaml` §4.3), but every default is overridable via kwargs.
    """

    __slots__ = ("strategy", "head_lines", "tail_lines")

    def __init__(
        self,
        strategy: TruncatorStrategy | None = None,
        head_lines: int | None = None,
        tail_lines: int | None = None,
    ) -> None:
        cfg_strategy, cfg_head, cfg_tail = _strategy_from_config()
        self.strategy: TruncatorStrategy = strategy or cfg_strategy
        self.head_lines: int = head_lines if head_lines is not None else cfg_head
        self.tail_lines: int = tail_lines if tail_lines is not None else cfg_tail
        if self.head_lines < 1 or self.tail_lines < 1:
            raise ValueError("head_lines and tail_lines must be >= 1")

    # --- public ---------------------------------------------------------

    def truncate(self, message: Message, max_lines: int | None = None) -> Message:
        """Truncate `message.content` and return a new Message with truncated=True.

        `max_lines` is the total line budget. When omitted, `head_lines + tail_lines`
        is used (i.e. the configured split).
        """
        if message.content is None:
            return message
        if max_lines is None:
            max_lines = self.head_lines + self.tail_lines
        if max_lines < 1:
            raise ValueError("max_lines must be >= 1")

        lines = _split_lines(message.content)
        if len(lines) <= max_lines:
            return message

        if self.strategy == _STRATEGY_HEAD_TAIL:
            new_lines, _dropped = _head_tail_truncate(
                lines, self.head_lines, self.tail_lines
            )
        elif self.strategy == _STRATEGY_MIDDLE_OUT:
            new_lines, _dropped = _middle_out_truncate(lines, max_lines)
        elif self.strategy == _STRATEGY_SUMMARIZE:
            # v0.1: head_tail fallback. v0.3+ will call an LLM here.
            new_lines, _dropped = _head_tail_truncate(
                lines, self.head_lines, self.tail_lines
            )
        else:
            raise ValueError(f"Unknown truncator strategy: {self.strategy}")

        return Message(
            role=message.role,
            content=_join_lines(new_lines),
            tool_calls=message.tool_calls,
            tool_call_id=message.tool_call_id,
            tool_name=message.tool_name,
            name=message.name,
            timestamp=message.timestamp,
            token_count=message.token_count,
            finish_reason=message.finish_reason,
            reasoning=message.reasoning,
            cache_breakpoint=message.cache_breakpoint,
            compressed=message.compressed,
            truncated=True,
            system=message.system,
            tool=message.tool,
        )
