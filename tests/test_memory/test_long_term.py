"""Tests for hello_agent.memory.long_term.LongTermMemory."""
from __future__ import annotations

from pathlib import Path

import pytest

from hello_agent.memory.long_term import LongTermMemory


@pytest.fixture()
def lt(tmp_path: Path) -> LongTermMemory:
    """Fresh LongTermMemory on a tmp sqlite file."""
    mem = LongTermMemory(db_path=tmp_path / "lt.db")
    yield mem
    mem.close()


# --- basic CRUD --------------------------------------------------------------


def test_set_and_get_string_fact(lt: LongTermMemory) -> None:
    rid = lt.set_fact("editor", "vscode", source="user")
    assert rid > 0
    assert lt.get_fact("editor") == "vscode"


def test_set_and_get_int_fact(lt: LongTermMemory) -> None:
    lt.set_fact("count", 3, source="test")
    assert lt.get_fact("count") == 3


def test_set_and_get_dict_fact(lt: LongTermMemory) -> None:
    payload = {"theme": "dark", "font_size": 14}
    lt.set_fact("prefs", payload, source="user")
    assert lt.get_fact("prefs") == payload


def test_get_fact_returns_default_when_missing(lt: LongTermMemory) -> None:
    assert lt.get_fact("nope", default="default-value") == "default-value"
    assert lt.get_fact("nope") is None


def test_set_fact_rejects_empty_key(lt: LongTermMemory) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        lt.set_fact("", "value")


# --- upsert ------------------------------------------------------------------


def test_set_fact_upserts_by_key(lt: LongTermMemory) -> None:
    """Re-setting the same key updates the value, doesn't add a row."""
    lt.set_fact("editor", "vscode", source="user")
    lt.set_fact("editor", "zed", source="user")
    assert lt.get_fact("editor") == "zed"
    assert lt.count() == 1


def test_upsert_updates_source_and_timestamp(lt: LongTermMemory) -> None:
    lt.set_fact("editor", "vscode", source="user")
    row1 = lt.get_fact_row("editor")
    assert row1 is not None
    assert row1["source"] == "user"

    lt.set_fact("editor", "vscode", source="config")
    row2 = lt.get_fact_row("editor")
    assert row2 is not None
    assert row2["source"] == "config"
    # updated_at should be >= created_at.
    assert row2["updated_at"] >= row2["created_at"]


# --- list / search / count ---------------------------------------------------


def test_list_facts_returns_all(lt: LongTermMemory) -> None:
    lt.set_fact("a", "1")
    lt.set_fact("b", "2")
    lt.set_fact("c", "3")
    facts = lt.list_facts()
    assert {f["key"] for f in facts} == {"a", "b", "c"}


def test_list_facts_filters_by_source(lt: LongTermMemory) -> None:
    lt.set_fact("a", "1", source="user")
    lt.set_fact("b", "2", source="user")
    lt.set_fact("c", "3", source="config")
    user_facts = lt.list_facts(source="user")
    assert {f["key"] for f in user_facts} == {"a", "b"}


def test_search_substring_matches_key_and_value(lt: LongTermMemory) -> None:
    lt.set_fact("favorite_editor", "vscode")
    lt.set_fact("favorite_font", "fira code")
    lt.set_fact("theme", "vscode-dark-plus")
    hits = lt.search("vscode")
    assert {h["key"] for h in hits} >= {"favorite_editor", "theme"}


def test_search_empty_query_returns_empty(lt: LongTermMemory) -> None:
    lt.set_fact("a", "1")
    assert lt.search("") == []


def test_count_returns_total_or_filtered(lt: LongTermMemory) -> None:
    assert lt.count() == 0
    lt.set_fact("a", "1", source="user")
    lt.set_fact("b", "2", source="user")
    lt.set_fact("c", "3", source="config")
    assert lt.count() == 3
    assert lt.count(source="user") == 2


# --- delete ------------------------------------------------------------------


def test_delete_fact_returns_true_when_existing(lt: LongTermMemory) -> None:
    lt.set_fact("a", "1")
    assert lt.delete_fact("a") is True
    assert lt.get_fact("a") is None


def test_delete_fact_returns_false_when_missing(lt: LongTermMemory) -> None:
    assert lt.delete_fact("nope") is False


# --- transaction & context manager ------------------------------------------


def test_transaction_commits_on_success(lt: LongTermMemory) -> None:
    with lt.transaction() as conn:
        # Use a string value that round-trips through JSON unchanged.
        # (The decoder JSON-loads the blob; raw "1" would become int 1.)
        conn.execute(
            "INSERT INTO facts (key, value, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("x", '"hello"', "test", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
    assert lt.get_fact("x") == "hello"


def test_transaction_rolls_back_on_exception(lt: LongTermMemory) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        with lt.transaction() as conn:
            conn.execute(
                "INSERT INTO facts (key, value, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("y", '"hello"', "test", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
            raise RuntimeError("boom")
    assert lt.get_fact("y") is None


def test_context_manager_closes_connection(tmp_path: Path) -> None:
    with LongTermMemory(db_path=tmp_path / "ctx.db") as mem:
        mem.set_fact("a", "1")
        assert mem.get_fact("a") == "1"
    # After the `with`, the connection is closed; further use would re-open.
    # Use the public API: re-open with the same path.
    with LongTermMemory(db_path=tmp_path / "ctx.db") as mem2:
        assert mem2.get_fact("a") == "1"


# --- default path resolution -------------------------------------------------


def test_db_path_defaults_under_hello_agent_home(
    tmp_hello_agent_home: Path, reset_singletons: None
) -> None:
    """When `db_path` is None, the file lives at `$HELLO_AGENT_HOME/memory/long_term.db`."""
    mem = LongTermMemory()
    try:
        expected = (tmp_hello_agent_home / "memory" / "long_term.db").resolve()
        assert mem.db_path.resolve() == expected
        # And the parent dir was created.
        assert mem.db_path.parent.is_dir()
    finally:
        mem.close()
