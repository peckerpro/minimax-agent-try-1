"""Short-term memory.

Per the Day-4 spec (ENGINEERING.md §6.6), `short_term.py` is the in-memory
scratchpad for the active session:

- A `HistoryManager` (from `context/history.py`) holds the conversation
  with sliding-window eviction.
- A small `name -> value` dict holds **facts** that the agent wants to
  remember across the session but NOT persist to disk. The Day-4 API is
  `add_fact(name, value)`, `get_fact(name)`, `list_facts()`, with a
  `persist()` hook to push a subset of facts to long-term storage.

The class is a thin wrapper; consumers that only need the message buffer
can use `ShortTermMemory.history` (a `HistoryManager`) directly.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from hello_agent.context.history import HistoryManager
from hello_agent.core.types import Message

if TYPE_CHECKING:
    from hello_agent.memory.long_term import LongTermMemory


class ShortTermMemory:
    """In-memory scratchpad for one session.

    Attributes
    ----------
    history : HistoryManager
        The conversation sliding-window. Day 4 reads `max_messages` from
        `config.memory.short_term_max_messages` via the manager's default
        constructor.
    facts : dict[str, Any]
        In-conversation name -> value facts. Cleared on `clear()`.
    """

    __slots__ = ("history", "facts", "_persisted_keys")

    def __init__(self, max_messages: int | None = None) -> None:
        self.history = HistoryManager(max_messages=max_messages)
        self.facts: dict[str, Any] = {}
        # Keys that `persist()` has already pushed; prevent re-pushing the
        # same fact on every session-end hook.
        self._persisted_keys: set[str] = set()

    # --- message buffer delegation ---------------------------------------

    def append_message(self, message: Message) -> None:
        self.history.append(message)

    def messages(self) -> list[Message]:
        return self.history.to_list()

    # --- fact API (Day-4 spec §6.6) --------------------------------------

    def add_fact(self, name: str, value: Any) -> None:
        """Add or update a named fact. Overwrites any previous value."""
        self.facts[name] = value

    def get_fact(self, name: str, default: Any = None) -> Any:
        return self.facts.get(name, default)

    def list_facts(self) -> dict[str, Any]:
        """Return a copy of the current facts dict (caller cannot mutate us)."""
        return dict(self.facts)

    def remove_fact(self, name: str) -> bool:
        """Remove a fact; return True if it existed."""
        existed = name in self.facts
        self.facts.pop(name, None)
        self._persisted_keys.discard(name)
        return existed

    # --- session lifecycle ----------------------------------------------

    def clear(self) -> None:
        """Wipe both the message buffer and the in-memory facts."""
        self.history.clear()
        self.facts.clear()
        self._persisted_keys.clear()

    def persist(self, long_term: LongTermMemory, *, only_unpersisted: bool = True) -> int:
        """Push all (or only un-persisted) facts to `long_term`.

        Returns the number of facts written. A fact whose name+value pair
        is identical to the one already on disk is silently skipped.
        """
        written = 0
        for name, value in self.facts.items():
            if only_unpersisted and name in self._persisted_keys:
                continue
            try:
                long_term.set_fact(key=name, value=value, source="short_term")
            except Exception:  # noqa: BLE001 — best-effort persistence
                continue
            self._persisted_keys.add(name)
            written += 1
        return written

    # --- iteration conveniences ------------------------------------------

    def __iter__(self) -> Iterator[Message]:
        return iter(self.history)
