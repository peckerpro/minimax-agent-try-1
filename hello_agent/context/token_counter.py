"""Token counting for context budgeting.

Public API:

- `TokenCounter(model: str = "gpt-4o-mini")` — class-based counter that
  lazily resolves a tiktoken `Encoding` for the named model and falls back
  to `cl100k_base` for unknown models. If `tiktoken` is missing entirely
  (e.g. stripped-down install), the counter transparently uses a
  `len(text) / 4` heuristic.

- Module-level `count_tokens(messages, model=...)` — convenience wrapper
  used by the agent loop without instantiating a class.

The estimate is intentionally simple: 4 tokens of per-message overhead
(role + delimiters) plus the encoded content tokens. Good enough for
budget tracking; not an exact count of any specific LLM's input.
"""
from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from hello_agent.core.types import Message

_FALLBACK_ENCODING = "cl100k_base"
_PER_MESSAGE_OVERHEAD = 4
_HEURISTIC_CHARS_PER_TOKEN = 4  # OpenAI rule of thumb


def _tiktoken_available() -> bool:
    try:
        import tiktoken  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 — tiktoken missing or broken
        return False


@lru_cache(maxsize=8)
def _get_encoding(model: str):
    """Resolve a tiktoken Encoding for `model`, falling back to cl100k_base.

    Returns None if tiktoken is unavailable — callers must handle the
    heuristic path in that case.
    """
    if not _tiktoken_available():
        return None
    import tiktoken

    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        try:
            return tiktoken.get_encoding(_FALLBACK_ENCODING)
        except Exception:  # noqa: BLE001
            return None


def count_text_tokens(text: str | None, model: str = "gpt-4o-mini") -> int:
    """Count tokens for a single text string.

    Returns 0 for `None` / empty input. Falls back to `len(text) / 4` if
    tiktoken is unavailable.
    """
    if not text:
        return 0
    enc = _get_encoding(model)
    if enc is None:
        return max(1, len(text) // _HEURISTIC_CHARS_PER_TOKEN)
    try:
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001
        return max(1, len(text) // _HEURISTIC_CHARS_PER_TOKEN)


def count_tokens(
    messages: Iterable[Message] | Message,
    model: str = "gpt-4o-mini",
) -> int:
    """Count tokens for a list of messages (or a single message).

    Uses a simplified per-message estimate: 4 tokens of overhead (role +
    metadata) plus the content tokens. Tool-call argument JSON is also
    encoded. Good enough for budget tracking; not exact.
    """
    if isinstance(messages, Message):
        messages = [messages]
    enc = _get_encoding(model)
    total = 0
    for m in messages:
        total += _PER_MESSAGE_OVERHEAD  # role + delimiters
        if m.content:
            if enc is not None:
                try:
                    total += len(enc.encode(m.content))
                    continue
                except Exception:  # noqa: BLE001
                    pass
            total += max(1, len(m.content) // _HEURISTIC_CHARS_PER_TOKEN)
        if m.tool_calls:
            for tc in m.tool_calls:
                arg_blob = str(tc.arguments) if tc.arguments is not None else ""
                if enc is not None:
                    try:
                        total += len(enc.encode(tc.name))
                        total += len(enc.encode(arg_blob))
                        continue
                    except Exception:  # noqa: BLE001
                        pass
                total += max(1, len(tc.name) // _HEURISTIC_CHARS_PER_TOKEN)
                total += max(1, len(arg_blob) // _HEURISTIC_CHARS_PER_TOKEN)
    return total


class TokenCounter:
    """Token counter bound to a specific model.

    Usage:
        counter = TokenCounter(model="gpt-4o-mini")
        n = counter.count(messages)
        n_text = counter.count_text("hello world")
        # Heuristic-only mode (skip tiktoken lookup) — useful for tests
        # that want deterministic behavior without network/file IO.
        heuristic_counter = TokenCounter(use_tiktoken=False)
    """

    __slots__ = ("model", "_use_tiktoken", "_enc")

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        *,
        use_tiktoken: bool = True,
    ) -> None:
        self.model = model
        self._use_tiktoken = use_tiktoken
        self._enc = None
        if use_tiktoken:
            self._enc = _get_encoding(model)

    @property
    def using_heuristic(self) -> bool:
        """True if this counter will fall back to chars/4 (no tiktoken)."""
        return self._enc is None

    def count_text(self, text: str | None) -> int:
        """Count tokens for a single text string."""
        if not text:
            return 0
        if self._enc is not None:
            try:
                return len(self._enc.encode(text))
            except Exception:  # noqa: BLE001
                pass
        return max(1, len(text) // _HEURISTIC_CHARS_PER_TOKEN)

    def count(self, messages: Iterable[Message] | Message) -> int:
        """Count tokens for a list (or single) of messages.

        Same heuristic as the module-level `count_tokens`, but uses the
        cached encoding on this instance (faster for repeated calls).
        """
        if isinstance(messages, Message):
            messages = [messages]
        total = 0
        for m in messages:
            total += _PER_MESSAGE_OVERHEAD
            if m.content:
                total += self.count_text(m.content)
            if m.tool_calls:
                for tc in m.tool_calls:
                    arg_blob = str(tc.arguments) if tc.arguments is not None else ""
                    total += self.count_text(tc.name)
                    total += self.count_text(arg_blob)
        return total

    # --- introspection helpers (handy for the builder) ------------------

    def fits(self, messages: Iterable[Message], budget: int) -> bool:
        """True iff `count(messages) <= budget`."""
        return self.count(messages) <= budget

    def head_room(self, messages: Iterable[Message], budget: int) -> int:
        """How many tokens of `budget` remain after `messages`."""
        return budget - self.count(messages)
