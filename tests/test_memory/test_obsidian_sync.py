"""Tests for hello_agent.memory.obsidian_sync.ObsidianSync.

Covers the v0.2 scaffold (no-op when vault unconfigured) and the
post-v0.2 enhancements (write-through from LongTermMemory, cross-day
filename stability, wikilink extraction, .md file format).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hello_agent.memory.obsidian_sync import (
    TAG_RE,
    WIKILINK_RE,
    ObsidianSync,
    _slugify,
)

# --- no-op scaffold (no vault configured) -----------------------------------


def test_init_without_vault_is_not_configured() -> None:
    """The default constructor reads `OBSIDIAN_VAULT_PATH` from config; in
    the test environment that's empty, so `is_configured()` is False."""
    sync = ObsidianSync()
    # Test sandbox sets `HELLO_AGENT_DOTENV_PATH` to a non-existent file,
    # so `obsidian_vault_path` resolves to empty.
    assert sync.is_configured() is False


def test_no_op_export_returns_none_when_not_configured() -> None:
    sync = ObsidianSync()
    assert (
        sync.export_memory(memory_id="k", content="body", kind="fact") is None
    )


def test_no_op_list_returns_empty_when_not_configured() -> None:
    assert ObsidianSync().list_memories() == []


def test_no_op_get_returns_none_when_not_configured() -> None:
    assert ObsidianSync().get_memory("k") is None


def test_no_op_delete_returns_false_when_not_configured() -> None:
    assert ObsidianSync().delete_memory("k") is False


def test_no_op_extract_relations_returns_empty_when_not_configured() -> None:
    assert ObsidianSync().extract_relations() == {}


# --- explicit vault ----------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """A fresh vault directory under tmp."""
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture()
def sync(vault: Path) -> ObsidianSync:
    """An ObsidianSync pointed at the temp vault."""
    return ObsidianSync(vault_path=vault)


# --- write / read -----------------------------------------------------------


def test_export_writes_markdown_file(sync: ObsidianSync, vault: Path) -> None:
    path = sync.export_memory(memory_id="k1", content="hello world", kind="fact")
    assert path is not None
    assert Path(path).exists()
    # The file lives in <vault>/memory/<YYYY-MM-DD>_<slug>.md
    rel = Path(path).relative_to(vault)
    assert rel.parts[0] == "memory"
    assert rel.name.endswith("_k1.md")


def test_export_creates_yaml_frontmatter(sync: ObsidianSync) -> None:
    path = sync.export_memory(
        memory_id="editor_choice",
        content="vscode",
        kind="fact",
        title="Editor choice",
        tags=["preference"],
    )
    assert path is not None
    text = Path(path).read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "id: editor_choice" in text
    assert "kind: fact" in text
    assert "title: Editor choice" in text
    assert "vscode" in text  # body


def test_export_uses_supplied_title(sync: ObsidianSync) -> None:
    path = sync.export_memory(
        memory_id="k1", content="body", kind="fact", title="My Custom Title"
    )
    assert path is not None
    text = Path(path).read_text(encoding="utf-8")
    assert "title: My Custom Title" in text


def test_export_extracts_wikilinks_from_content(sync: ObsidianSync) -> None:
    body = "I use [[vscode]] daily and sometimes [[vim]]"
    path = sync.export_memory(memory_id="k1", content=body, kind="fact")
    assert path is not None
    text = Path(path).read_text(encoding="utf-8")
    # Wikilinks get a "## Related" section appended.
    assert "## Related" in text
    assert "[[vscode]]" in text
    assert "[[vim]]" in text


def test_export_extracts_inline_tags_from_content(sync: ObsidianSync) -> None:
    body = "I prefer dark mode #ui #preference for coding"
    path = sync.export_memory(memory_id="k1", content=body, kind="fact")
    assert path is not None
    text = Path(path).read_text(encoding="utf-8")
    # Tags appear in frontmatter (sorted alphabetically).
    assert "ui" in text
    assert "preference" in text


def test_export_merges_supplied_and_inline_tags(sync: ObsidianSync) -> None:
    path = sync.export_memory(
        memory_id="k1",
        content="see #inline-tag",
        kind="fact",
        tags=["user-tag"],
    )
    assert path is not None
    text = Path(path).read_text(encoding="utf-8")
    # Both tags appear in the frontmatter.
    assert "user-tag" in text
    assert "inline-tag" in text


def test_export_accepts_string_value_with_no_json_quoting(sync: ObsidianSync) -> None:
    """Plain string content is written verbatim — no extra JSON quoting."""
    path = sync.export_memory(memory_id="k1", content="just a string", kind="fact")
    assert path is not None
    text = Path(path).read_text(encoding="utf-8")
    # The body line should not be wrapped in JSON quotes.
    assert "just a string" in text
    # And it shouldn't appear in the frontmatter as a quoted value.
    assert "'just a string'" not in text


# --- list / get -------------------------------------------------------------


def test_list_memories_returns_exported(sync: ObsidianSync) -> None:
    sync.export_memory(memory_id="a", content="A", kind="fact")
    sync.export_memory(memory_id="b", content="B", kind="fact", title="B-title")
    listed = sync.list_memories()
    ids = {m["id"] for m in listed}
    assert ids == {"a", "b"}


def test_list_memories_includes_frontmatter_summary(
    sync: ObsidianSync, vault: Path
) -> None:
    sync.export_memory(
        memory_id="k1", content="body", kind="preference", title="K1"
    )
    listed = sync.list_memories()
    assert len(listed) == 1
    item = listed[0]
    assert item["id"] == "k1"
    assert item["kind"] == "preference"
    assert item["title"] == "K1"
    assert "path" in item
    assert Path(item["path"]).is_relative_to(vault)


def test_get_memory_returns_full_record(sync: ObsidianSync) -> None:
    sync.export_memory(
        memory_id="k1",
        content="body text",
        kind="fact",
        title="K1",
        tags=["t1"],
    )
    record = sync.get_memory("k1")
    assert record is not None
    assert "body text" in record["content"]
    assert record["frontmatter"]["id"] == "k1"
    assert record["frontmatter"]["kind"] == "fact"
    assert "t1" in record["frontmatter"]["tags"]


def test_get_memory_returns_none_for_missing(sync: ObsidianSync) -> None:
    assert sync.get_memory("nope") is None


# --- delete -----------------------------------------------------------------


def test_delete_memory_removes_file(sync: ObsidianSync) -> None:
    path = sync.export_memory(memory_id="k1", content="body", kind="fact")
    assert path is not None
    assert Path(path).exists()
    assert sync.delete_memory("k1") is True
    assert not Path(path).exists()


def test_delete_memory_returns_false_for_missing(sync: ObsidianSync) -> None:
    assert sync.delete_memory("nope") is False


# --- cross-day dedup --------------------------------------------------------


def test_re_export_keeps_original_filename(sync: ObsidianSync) -> None:
    """Re-exporting the same memory_id on a later day must overwrite the
    original file in place, not create a duplicate with a new date."""
    path1 = sync.export_memory(memory_id="k1", content="v1", kind="fact")
    assert path1 is not None
    # Second export: same id, no "next day" needed — the dedup is
    # triggered by the existence of a same-id .md in the memory dir.
    path2 = sync.export_memory(memory_id="k1", content="v2", kind="fact")
    assert path2 is not None
    assert Path(path1).resolve() == Path(path2).resolve(), (
        "export_memory should update the same file in place when id already exists"
    )
    # No duplicates on disk.
    files = list(Path(path1).parent.glob("*.md"))
    assert len(files) == 1
    # And the body reflects the latest value.
    assert "v2" in Path(path1).read_text(encoding="utf-8")


# --- extract_relations ------------------------------------------------------


def test_extract_relations_returns_wikilink_graph(sync: ObsidianSync) -> None:
    sync.export_memory(memory_id="a", content="links to [[b]]", kind="fact")
    sync.export_memory(memory_id="b", content="links to [[a]] and [[c]]", kind="fact")
    rels = sync.extract_relations()
    assert set(rels["a"]) == {"b"}
    assert set(rels["b"]) == {"a", "c"}


# --- introspection ----------------------------------------------------------


def test_last_export_tracks_writes(sync: ObsidianSync) -> None:
    assert sync.last_export == {}
    sync.export_memory(memory_id="a", content="A", kind="fact")
    sync.export_memory(memory_id="b", content="B", kind="fact")
    assert set(sync.last_export.keys()) == {"a", "b"}


# --- pure helpers -----------------------------------------------------------


def test_slugify_lowercases_and_replaces_special_chars() -> None:
    assert _slugify("Hello World") == "hello-world"
    assert _slugify("foo_bar") == "foo-bar"
    assert _slugify("   leading-trailing   ") == "leading-trailing"
    assert _slugify("---") == "memory"  # empty fallback
    assert _slugify("a" * 200, max_len=10) == "a" * 10


def test_wikilink_regex_extracts_brackets() -> None:
    assert WIKILINK_RE.findall("see [[a]] and [[b/c]]") == ["a", "b/c"]


def test_tag_regex_extracts_hash_tags() -> None:
    assert TAG_RE.findall("a #one b #two-three c") == ["one", "two-three"]
    # No leading hash.
    assert TAG_RE.findall("nothere") == []
