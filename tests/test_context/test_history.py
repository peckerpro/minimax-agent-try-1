"""Tests for hello_agent.context.history.HistoryManager."""
from __future__ import annotations

import pytest

from hello_agent.context.history import HistoryManager
from hello_agent.core.types import Message, Role

# --- construction & invariants -----------------------------------------------


def test_default_max_messages_is_50() -> None:
    """The spec (§6.5) says default `max_messages=50` from config.

    With no config.yaml present, the built-in default is 50.
    """
    hm = HistoryManager()
    assert hm.max_messages == 50


def test_max_messages_must_be_positive() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        HistoryManager(max_messages=0)
    with pytest.raises(ValueError, match=">= 1"):
        HistoryManager(max_messages=-1)


# --- sliding window ----------------------------------------------------------


def test_append_enforces_sliding_window() -> None:
    """Pushing more than `max_messages` drops the oldest non-system entry."""
    hm = HistoryManager(max_messages=3)
    for i in range(5):
        hm.append(Message(role=Role.USER, content=f"m{i}"))
    assert len(hm) == 3
    contents = [m.content for m in hm.to_list()]
    assert contents == ["m2", "m3", "m4"]


def test_sliding_window_at_sixty_messages() -> None:
    """The Day-4 spec test: push 60 messages, assert len == 50."""
    hm = HistoryManager(max_messages=50)
    for i in range(60):
        hm.append(Message(role=Role.USER, content=f"m{i}"))
    assert len(hm) == 50
    assert hm.to_list()[0].content == "m10"
    assert hm.to_list()[-1].content == "m59"


def test_system_message_survives_eviction() -> None:
    """The leading system message is never dropped by sliding-window."""
    hm = HistoryManager(max_messages=3)
    hm.set_system("you are brief")
    for i in range(10):
        hm.append(Message(role=Role.USER, content=f"u{i}"))
    sys_msg = hm.system_message()
    assert sys_msg is not None
    assert sys_msg.content == "you are brief"


def test_compressed_messages_are_not_evicted() -> None:
    """A `compressed=True` message is treated as historical ground truth."""
    hm = HistoryManager(max_messages=3)
    hm.set_system("sys")
    hm.append(Message(role=Role.USER, content="a", compressed=True))
    hm.append(Message(role=Role.USER, content="b"))
    hm.append(Message(role=Role.USER, content="c"))
    hm.append(Message(role=Role.USER, content="d"))  # should evict "b", not "a"
    contents = [m.content for m in hm.to_list()]
    assert "a" in contents
    assert "b" not in contents
    assert "d" in contents


# --- flag-aware helpers ------------------------------------------------------


def test_mark_compressed_sets_flag_and_replaces() -> None:
    """`mark_compressed` flips the flag and (if needed) inserts the message."""
    hm = HistoryManager(max_messages=10)
    msg = Message(role=Role.USER, content="summary of past 20 turns")
    hm.mark_compressed(msg)
    assert msg.compressed is True
    assert any(m is msg for m in hm.to_list())


def test_mark_truncated_sets_flag() -> None:
    hm = HistoryManager(max_messages=10)
    msg = Message(role=Role.TOOL, content="... [truncated] ...")
    hm.mark_truncated(msg)
    assert msg.truncated is True


def test_compressed_and_truncated_count() -> None:
    hm = HistoryManager(max_messages=10)
    hm.append(Message(role=Role.USER, content="a", compressed=True))
    hm.append(Message(role=Role.USER, content="b", truncated=True))
    hm.append(Message(role=Role.USER, content="c"))
    assert hm.compressed_count() == 1
    assert hm.truncated_count() == 1


# --- misc --------------------------------------------------------------------


def test_clear_empties_history() -> None:
    hm = HistoryManager(max_messages=5)
    for i in range(3):
        hm.append(Message(role=Role.USER, content=f"x{i}"))
    hm.clear()
    assert len(hm) == 0


def test_replace_atomic_swap() -> None:
    hm = HistoryManager(max_messages=5)
    for i in range(3):
        hm.append(Message(role=Role.USER, content=f"old{i}"))
    new = [Message(role=Role.USER, content=f"new{i}") for i in range(2)]
    hm.replace(new)
    assert [m.content for m in hm.to_list()] == ["new0", "new1"]


def test_set_system_replaces_existing() -> None:
    hm = HistoryManager(max_messages=5)
    hm.set_system("first")
    hm.set_system("second")
    assert hm.system_message() is not None
    assert hm.system_message().content == "second"
    # And there's only one system message.
    sys_count = sum(1 for m in hm if m.role == Role.SYSTEM)
    assert sys_count == 1


def test_iteration_yields_messages_in_order() -> None:
    hm = HistoryManager(max_messages=5)
    for i in range(3):
        hm.append(Message(role=Role.USER, content=f"m{i}"))
    assert [m.content for m in hm] == ["m0", "m1", "m2"]


def test_getitem_supports_indexing() -> None:
    hm = HistoryManager(max_messages=5)
    for i in range(3):
        hm.append(Message(role=Role.USER, content=f"m{i}"))
    assert hm[0].content == "m0"
    assert hm[2].content == "m2"
