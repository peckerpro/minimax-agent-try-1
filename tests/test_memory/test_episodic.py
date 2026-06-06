"""Tests for hello_agent.memory.episodic.EpisodicMemory."""
from __future__ import annotations

from pathlib import Path

import pytest

from hello_agent.memory.episodic import EpisodicMemory


@pytest.fixture()
def ep(tmp_path: Path) -> EpisodicMemory:
    """Fresh EpisodicMemory on a tmp sqlite file."""
    mem = EpisodicMemory(db_path=tmp_path / "ep.db", summarize_every_n_turns=20)
    yield mem
    mem.close()


# --- record + list -----------------------------------------------------------


def test_record_and_list_single_episode(ep: EpisodicMemory) -> None:
    eid = ep.record_episode("sess-1", "helped user install zed")
    assert eid > 0
    recent = ep.list_recent(limit=10)
    assert len(recent) == 1
    assert recent[0]["session_id"] == "sess-1"
    assert recent[0]["summary"] == "helped user install zed"
    assert "id" in recent[0]
    assert "created_at" in recent[0]


def test_list_recent_returns_newest_first(ep: EpisodicMemory) -> None:
    ep.record_episode("s1", "first")
    ep.record_episode("s1", "second")
    ep.record_episode("s1", "third")
    recent = ep.list_recent(limit=10)
    summaries = [e["summary"] for e in recent]
    assert summaries == ["third", "second", "first"]


def test_list_recent_respects_limit(ep: EpisodicMemory) -> None:
    for i in range(5):
        ep.record_episode("s", f"e{i}")
    assert len(ep.list_recent(limit=2)) == 2
    assert len(ep.list_recent(limit=100)) == 5


def test_list_recent_filters_by_session_id(ep: EpisodicMemory) -> None:
    ep.record_episode("a", "from-a-1")
    ep.record_episode("b", "from-b-1")
    ep.record_episode("a", "from-a-2")
    a_only = ep.list_recent(session_id="a", limit=10)
    assert {e["summary"] for e in a_only} == {"from-a-1", "from-a-2"}


# --- search ------------------------------------------------------------------


def test_search_substring_match(ep: EpisodicMemory) -> None:
    ep.record_episode("s", "fixed a numpy broadcasting issue")
    ep.record_episode("s", "translated a poem")
    ep.record_episode("s", "rewrote a numpy reduction")
    hits = ep.search("numpy")
    assert len(hits) == 2
    assert all("numpy" in h["summary"] for h in hits)


def test_search_empty_query_returns_empty(ep: EpisodicMemory) -> None:
    ep.record_episode("s", "x")
    assert ep.search("") == []


# --- count -------------------------------------------------------------------


def test_count_returns_total(ep: EpisodicMemory) -> None:
    assert ep.count() == 0
    ep.record_episode("a", "x")
    ep.record_episode("b", "y")
    assert ep.count() == 2


def test_count_filters_by_session_id(ep: EpisodicMemory) -> None:
    ep.record_episode("a", "x")
    ep.record_episode("a", "y")
    ep.record_episode("b", "z")
    assert ep.count(session_id="a") == 2
    assert ep.count(session_id="b") == 1


# --- should_summarize --------------------------------------------------------


def test_should_summarize_returns_true_on_multiples(ep: EpisodicMemory) -> None:
    """The Day-4 spec: `summarize_every_n_turns=20` → true at 20, 40, 60..."""
    assert ep.should_summarize(0) is False
    assert ep.should_summarize(20) is True
    assert ep.should_summarize(40) is True
    assert ep.should_summarize(60) is True
    assert ep.should_summarize(10) is False
    assert ep.should_summarize(15) is False


def test_should_summarize_respects_custom_n(tmp_path: Path) -> None:
    ep = EpisodicMemory(db_path=tmp_path / "n.db", summarize_every_n_turns=5)
    try:
        assert ep.should_summarize(5) is True
        assert ep.should_summarize(10) is True
        assert ep.should_summarize(7) is False
    finally:
        ep.close()


def test_should_summarize_disabled_when_zero() -> None:
    """`summarize_every_n_turns <= 0` means 'never summarize'."""
    from hello_agent.memory.episodic import EpisodicMemory

    # We don't even need a real db for this — the method is pure.
    # But the constructor tries to resolve a default db path; bypass it.
    class _Stub:
        summarize_every_n_turns = 0

    stub = _Stub()
    # Call the unbound method on the instance dict.
    # Equivalent to: `EpisodicMemory.should_summarize(stub, 100)` → False
    assert EpisodicMemory.should_summarize(stub, 100) is False  # type: ignore[arg-type]


# --- input validation --------------------------------------------------------


def test_record_rejects_empty_session_id(ep: EpisodicMemory) -> None:
    with pytest.raises(ValueError, match="session_id"):
        ep.record_episode("", "x")


def test_record_rejects_empty_summary(ep: EpisodicMemory) -> None:
    with pytest.raises(ValueError, match="summary"):
        ep.record_episode("s1", "")


# --- transactions / context manager -----------------------------------------


def test_transaction_commits_on_success(tmp_path: Path) -> None:
    with EpisodicMemory(db_path=tmp_path / "tx.db") as ep:
        with ep.transaction() as conn:
            conn.execute(
                "INSERT INTO episodes (session_id, summary, created_at) VALUES (?, ?, ?)",
                ("s", "x", "2026-01-01T00:00:00+00:00"),
            )
        assert ep.count() == 1


def test_transaction_rolls_back_on_exception(tmp_path: Path) -> None:
    with EpisodicMemory(db_path=tmp_path / "tx.db") as ep:
        with pytest.raises(RuntimeError, match="boom"):
            with ep.transaction() as conn:
                conn.execute(
                    "INSERT INTO episodes (session_id, summary, created_at) VALUES (?, ?, ?)",
                    ("s", "x", "2026-01-01T00:00:00+00:00"),
                )
                raise RuntimeError("boom")
        assert ep.count() == 0
