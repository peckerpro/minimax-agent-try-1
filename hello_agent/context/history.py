"""In-memory history manager with sliding window + per-message flags.

Per the Day-4 spec (ENGINEERING.md §6.5):

- `HistoryManager` keeps a deque of `Message` objects.
- `max_messages` is read from `config.memory.short_term_max_messages` (default 50)
  so the in-memory cache mirrors the YAML-declared budget.
- Per-message flags (compressed, truncated, system, tool) live on the `Message`
  itself (see `core/types.py`); this module exposes convenience helpers for
  inspecting and updating them.

Persistence is handled by `core/state.py`; this module is the in-memory cache
that the agent loop reads from.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

from hello_agent.core.types import Message, Role

if TYPE_CHECKING:
    from hello_agent.core.config import HelloAgentConfig

_DEFAULT_MAX_MESSAGES = 50


def _default_max_messages() -> int:
    """Read `memory.short_term_max_messages` from config; fall back to 50.

    Importing config is deferred so this module stays import-cheap for unit
    tests that don't want the side effects of `get_config()` (env reads, etc.).
    """
    try:
        from hello_agent.core.config import get_config

        cfg: HelloAgentConfig = get_config()
        n = int(cfg.memory.short_term_max_messages)
        return n if n > 0 else _DEFAULT_MAX_MESSAGES
    except Exception:  # noqa: BLE001 — best-effort; we always have a sane default
        return _DEFAULT_MAX_MESSAGES


class HistoryManager:
    """Sliding-window message history.

    `max_messages` includes the system message(s) at index 0. When the cap is
    reached, the oldest non-system message is dropped.

    The class is flag-aware: it never drops messages whose `compressed` flag is
    True (we always want to keep our digests in the window), and exposes
    `mark_compressed` / `mark_truncated` helpers that the summarizer and
    truncator call after rewriting content.
    """

    def __init__(self, max_messages: int | None = None) -> None:
        if max_messages is None:
            max_messages = _default_max_messages()
        if max_messages < 1:
            raise ValueError("max_messages must be >= 1")
        self.max_messages = max_messages
        # deque of Message. The system prompt (if any) sits at index 0.
        self._messages: deque[Message] = deque()

    # --- python protocol -------------------------------------------------

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self) -> Iterator[Message]:
        return iter(self._messages)

    def __getitem__(self, idx: int) -> Message:
        return self._messages[idx]

    # --- mutation --------------------------------------------------------

    def append(self, message: Message) -> None:
        """Append a message and enforce the sliding window.

        Compressed messages are never dropped (the system prompt digest is
        valuable history). All other messages are dropped oldest-first.
        """
        self._messages.append(message)
        self._enforce_window()

    def extend(self, messages: Iterable[Message]) -> None:
        for m in messages:
            self._messages.append(m)
        self._enforce_window()

    def to_list(self) -> list[Message]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def replace(self, messages: Iterable[Message]) -> None:
        """Atomically replace the entire history (e.g. after resuming from disk)."""
        self._messages.clear()
        self.extend(messages)

    def system_message(self) -> Message | None:
        for m in self._messages:
            if m.role == Role.SYSTEM:
                return m
        return None

    def set_system(self, content: str) -> None:
        """Insert or replace the leading system message."""
        if self._messages and self._messages[0].role == Role.SYSTEM:
            self._messages[0] = Message(role=Role.SYSTEM, content=content, system=True)
        else:
            self._messages.appendleft(Message(role=Role.SYSTEM, content=content, system=True))

    # --- per-message flag helpers (Day-4 spec) ---------------------------

    def mark_compressed(self, message: Message) -> Message:
        """Mark a message as compressed. Replaces it in the deque in-place.

        The caller is expected to have rewritten `message.content` to a digest
        before calling this. We return the same `Message` object for chaining.
        """
        message.compressed = True
        # Replace any existing copy in the deque (preserves order).
        for _i, m in enumerate(self._messages):
            if m is message:
                break
        else:
            # Not in the deque yet — append (will still fit within window).
            self._messages.append(message)
            self._enforce_window()
        return message

    def mark_truncated(self, message: Message) -> Message:
        """Mark a message as truncated (its body was shortened by truncator)."""
        message.truncated = True
        for _i, m in enumerate(self._messages):
            if m is message:
                break
        else:
            self._messages.append(message)
            self._enforce_window()
        return message

    def compressed_count(self) -> int:
        return sum(1 for m in self._messages if m.compressed)

    def truncated_count(self) -> int:
        return sum(1 for m in self._messages if m.truncated)

    # --- internal --------------------------------------------------------

    def _enforce_window(self) -> None:
        """Drop oldest non-system, non-compressed messages until len <= max.

        Order of eviction priority (drop first → drop last):
          1. non-compressed, non-system messages (oldest first)
          2. system messages (only if everything else is compressed)
        """
        while len(self._messages) > self.max_messages:
            dropped = False
            for i, m in enumerate(self._messages):
                if m.role == Role.SYSTEM:
                    continue
                if m.compressed:
                    # Keep compressed digests — they're the only historical
                    # ground truth we have for older turns.
                    continue
                del self._messages[i]
                dropped = True
                break
            if not dropped:
                # Either everything is a system message, or everything else
                # is compressed. We have to drop something; evict the oldest
                # non-compressed system message, or if none, the oldest
                # compressed one, or finally the very first message.
                if any(m.role == Role.SYSTEM for m in self._messages):
                    for i, m in enumerate(self._messages):
                        if m.role == Role.SYSTEM:
                            del self._messages[i]
                            dropped = True
                            break
                if not dropped:
                    self._messages.popleft()
