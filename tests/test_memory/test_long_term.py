"""Tests for hello_agent.memory.long_term.LongTermMemory."""
from __future__ import annotations

from pathlib import Path

import pytest

from hello_agent.memory.long_term import LongTermMemory
from hello_agent.memory.obsidian_sync import ObsidianSync


@pytest.fixture()
def lt(tmp_path: Path) -> LongTermMemory:
    """Fresh LongTermMemory on a tmp sqlite file (auto_reconcile=False
    so the test sandbox is not affected by the real vault)."""
    mem = LongTermMemory(db_path=tmp_path / "lt.db", auto_reconcile=False)
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


# --- vault write-through (mirror_to_vault) ---------------------------------
#
# The vault is wired via ObsidianSync's `vault_path=` constructor arg,
# NOT through the .env / config — that way tests stay isolated from the
# user's real `D:\hello_agent_obsidian_1`.


@pytest.fixture()
def lt_with_vault(tmp_path: Path) -> tuple[LongTermMemory, Path, ObsidianSync]:
    """LongTermMemory + a temp ObsidianSync pointed at the same tmp dir.

    The vault path is set via the `vault_path=` constructor so we don't
    touch the user's real vault. The LongTermMemory is constructed with
    `auto_reconcile=False`; tests that want to test reconcile call it
    explicitly.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    sync = ObsidianSync(vault_path=vault)
    mem = LongTermMemory(
        db_path=tmp_path / "lt.db",
        auto_reconcile=False,
        vault_path=vault,
    )
    try:
        yield mem, vault, sync
    finally:
        mem.close()


def test_set_fact_mirrors_to_vault(lt_with_vault: tuple[LongTermMemory, Path, ObsidianSync]) -> None:
    """A `set_fact` call also writes a `.md` file to the vault's memory subdir."""
    mem, vault, sync = lt_with_vault
    mem.set_fact("editor", "vscode", source="user")
    # The vault now has a markdown file for this fact.
    files = list((vault / "memory").glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "id: editor" in text
    assert "vscode" in text


def test_set_fact_mirror_to_vault_false_skips_write(
    lt_with_vault: tuple[LongTermMemory, Path, ObsidianSync]
) -> None:
    """`mirror_to_vault=False` writes only to SQLite — useful for tests
    and for the reconcile path that pulls FROM the vault."""
    mem, vault, _sync = lt_with_vault
    mem.set_fact("k1", "v1", source="user", mirror_to_vault=False)
    assert mem.get_fact("k1") == "v1"
    # No vault file was created.
    assert list((vault / "memory").glob("*.md")) == []


def test_set_fact_mirror_is_noop_when_vault_unconfigured(
    tmp_path: Path,
) -> None:
    """When the vault is NOT configured, mirror_to_vault is a no-op
    (no error, no file)."""
    mem = LongTermMemory(db_path=tmp_path / "lt.db", auto_reconcile=False)
    try:
        # In the test sandbox, OBSIDIAN_VAULT_PATH is empty.
        rid = mem.set_fact("k1", "v1", source="user")
        assert rid > 0
        # No exception, no file (the test sandbox has no vault path).
    finally:
        mem.close()


# --- reconcile_with_vault --------------------------------------------------


def test_reconcile_with_vault_returns_reason_when_unconfigured(
    tmp_path: Path,
) -> None:
    mem = LongTermMemory(db_path=tmp_path / "lt.db", auto_reconcile=False)
    try:
        result = mem.reconcile_with_vault()
        assert result["configured"] is False
        assert "reason" in result
    finally:
        mem.close()


def test_reconcile_adds_new_facts_from_vault(
    lt_with_vault: tuple[LongTermMemory, Path, ObsidianSync]
) -> None:
    """A fact that exists ONLY in the vault gets pulled into SQLite on reconcile."""
    mem, _vault, sync = lt_with_vault
    # Write a fact directly to the vault (simulates a user adding it
    # in Obsidian Desktop).
    sync.export_memory(memory_id="user_note", content="from obsidian", kind="fact")
    # SQLite is still empty.
    assert mem.count() == 0
    # Reconcile pulls it in.
    result = mem.reconcile_with_vault()
    assert result["configured"] is True
    assert result["added"] == 1
    assert result["updated"] == 0
    # And the fact is now visible via the normal API.
    assert mem.get_fact("user_note") == "from obsidian"
    # Source is "vault" so callers can tell where the row came from.
    row = mem.get_fact_row("user_note")
    assert row is not None
    assert row["source"] == "vault"


def test_reconcile_updates_existing_fact_when_vault_differs(
    lt_with_vault: tuple[LongTermMemory, Path, ObsidianSync]
) -> None:
    """If the user edits a fact in Obsidian, the vault value wins on reconcile."""
    mem, _vault, sync = lt_with_vault
    # Set a fact via the normal API (which also mirrors to vault).
    mem.set_fact("k1", "v1-old", source="user")
    # Now the user edits the file in Obsidian (or sync would write a
    # newer version). Simulate by re-exporting with a new value.
    sync.export_memory(memory_id="k1", content="v1-new", kind="fact")
    # Reconcile should detect the difference and update SQLite.
    result = mem.reconcile_with_vault()
    assert result["updated"] == 1
    assert mem.get_fact("k1") == "v1-new"


def test_reconcile_is_idempotent(
    lt_with_vault: tuple[LongTermMemory, Path, ObsidianSync]
) -> None:
    """Running reconcile twice in a row produces no changes on the 2nd call."""
    mem, _vault, sync = lt_with_vault
    sync.export_memory(memory_id="a", content="A", kind="fact")
    sync.export_memory(memory_id="b", content="B", kind="fact")
    first = mem.reconcile_with_vault()
    assert first["added"] == 2
    second = mem.reconcile_with_vault()
    assert second["added"] == 0
    assert second["updated"] == 0
    assert second["skipped"] == 2


def test_auto_reconcile_runs_lazily_on_first_read(
    lt_with_vault: tuple[LongTermMemory, Path, ObsidianSync],
) -> None:
    """When `auto_reconcile=True` (the default in production), the first
    read pulls vault facts in."""
    mem, vault, sync = lt_with_vault
    sync.export_memory(memory_id="from_vault", content="hello", kind="fact")
    # Replace the auto_reconcile=True instance, pointing it at the same vault.
    from hello_agent.memory.long_term import LongTermMemory as LTM

    mem2 = LTM(db_path=mem.db_path, auto_reconcile=True, vault_path=vault)
    try:
        # The first read triggers reconcile → fact appears.
        assert mem2.get_fact("from_vault") == "hello"
        assert mem2.get_fact_row("from_vault") is not None
    finally:
        mem2.close()


def test_auto_reconcile_only_runs_once(
    lt_with_vault: tuple[LongTermMemory, Path, ObsidianSync],
) -> None:
    """Subsequent reads do NOT re-trigger reconcile (one-shot flag)."""
    mem, vault, sync = lt_with_vault
    sync.export_memory(memory_id="k1", content="v1", kind="fact")
    from hello_agent.memory.long_term import LongTermMemory as LTM

    mem2 = LTM(db_path=mem.db_path, auto_reconcile=True, vault_path=vault)
    try:
        mem2.get_fact("k1")  # triggers reconcile
        # Add another vault-only fact AFTER the first read.
        sync.export_memory(memory_id="k2", content="v2", kind="fact")
        # k2 is NOT picked up — the one-shot flag has flipped.
        assert mem2.get_fact("k2") is None
    finally:
        mem2.close()
