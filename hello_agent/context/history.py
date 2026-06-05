"""In-memory history manager with sliding window.

Persistence is handled by `core/state.py`; this module is the in-memory cache
that the agent loop reads from. History itself is just a `list[Message]` with
helpers to window/append/clear.
"""
from __future__ import annotations

from collections import deque

from hello_agent.core.types import Message, Role


class HistoryManager:
    """Sliding-window message history.

    `max_messages` includes the system message(s) at index 0. When the cap is
    reached, the oldest non-system message is dropped.
    """

    def __init__(self, max_messages: int = 50):
        if max_messages < 1:
            raise ValueError("max_messages must be >= 1")
        self.max_messages = max_messages
        self._messages: deque[Message] = deque()

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self):
        return iter(self._messages)

    def append(self, message: Message) -> None:
        self._messages.append(message)
        self._enforce_window()

    def extend(self, messages: list[Message]) -> None:
        for m in messages:
            self._messages.append(m)
        self._enforce_window()

    def to_list(self) -> list[Message]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def replace(self, messages: list[Message]) -> None:
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
            self._messages[0] = Message(role=Role.SYSTEM, content=content)
        else:
            self._messages.appendleft(Message(role=Role.SYSTEM, content=content))

    def _enforce_window(self) -> None:
        """Drop oldest non-system messages until len <= max_messages."""
        while len(self._messages) > self.max_messages:
            # Find the oldest non-system message and drop it.
            for i, m in enumerate(self._messages):
                if m.role != Role.SYSTEM:
                    del self._messages[i]
                    break
            else:
                # All system messages — odd, but trim the oldest one to make progress.
                self._messages.popleft()
