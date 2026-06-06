"""Tests for hello_agent.memory.short_term.ShortTermMemory."""
from __future__ import annotations

from hello_agent.core.types import Message, Role
from hello_agent.memory.short_term import ShortTermMemory

# --- fact API ---------------------------------------------------------------


def test_add_and_get_fact() -> None:
    st = ShortTermMemory()
    st.add_fact("favorite_editor", "vscode")
    assert st.get_fact("favorite_editor") == "vscode"


def test_get_fact_returns_default_for_missing() -> None:
    st = ShortTermMemory()
    assert st.get_fact("nope") is None
    assert st.get_fact("nope", default="x") == "x"


def test_add_fact_overwrites() -> None:
    st = ShortTermMemory()
    st.add_fact("editor", "vscode")
    st.add_fact("editor", "zed")
    assert st.get_fact("editor") == "zed"


def test_list_facts_returns_copy() -> None:
    st = ShortTermMemory()
    st.add_fact("a", 1)
    st.add_fact("b", 2)
    facts = st.list_facts()
    assert facts == {"a": 1, "b": 2}
    # Mutating the returned dict must not affect the source.
    facts["c"] = 3
    assert "c" not in st.list_facts()


def test_remove_fact_returns_true_when_existing() -> None:
    st = ShortTermMemory()
    st.add_fact("a", 1)
    assert st.remove_fact("a") is True
    assert st.get_fact("a") is None


def test_remove_fact_returns_false_when_missing() -> None:
    st = ShortTermMemory()
    assert st.remove_fact("nope") is False


# --- history delegation -----------------------------------------------------


def test_append_message_uses_history_manager() -> None:
    st = ShortTermMemory(max_messages=3)
    for i in range(5):
        st.append_message(Message(role=Role.USER, content=f"m{i}"))
    assert len(st.messages()) == 3
    assert st.messages()[0].content == "m2"


def test_iteration_yields_messages() -> None:
    st = ShortTermMemory()
    for i in range(3):
        st.append_message(Message(role=Role.USER, content=f"m{i}"))
    assert [m.content for m in st] == ["m0", "m1", "m2"]


# --- clear ------------------------------------------------------------------


def test_clear_wipes_both_buffer_and_facts() -> None:
    st = ShortTermMemory()
    st.add_fact("a", 1)
    st.append_message(Message(role=Role.USER, content="x"))
    st.clear()
    assert st.list_facts() == {}
    assert st.messages() == []


# --- persist to long-term ---------------------------------------------------


def test_persist_writes_unpersisted_facts(tmp_path) -> None:
    from hello_agent.memory.long_term import LongTermMemory

    st = ShortTermMemory()
    st.add_fact("editor", "vscode")
    st.add_fact("language", "python")

    lt = LongTermMemory(db_path=tmp_path / "lt.db")
    try:
        written = st.persist(lt)
        assert written == 2
        assert lt.get_fact("editor") == "vscode"
        assert lt.get_fact("language") == "python"

        # Re-persist with only_unpersisted=True → no new writes.
        written2 = st.persist(lt)
        assert written2 == 0
    finally:
        lt.close()


def test_persist_can_force_rewrite(tmp_path) -> None:
    from hello_agent.memory.long_term import LongTermMemory

    st = ShortTermMemory()
    st.add_fact("editor", "vscode")
    lt = LongTermMemory(db_path=tmp_path / "lt.db")
    try:
        st.persist(lt)
        st.add_fact("editor", "zed")
        # only_unpersisted=False (force) → updates.
        written = st.persist(lt, only_unpersisted=False)
        assert written == 1
        assert lt.get_fact("editor") == "zed"
    finally:
        lt.close()
