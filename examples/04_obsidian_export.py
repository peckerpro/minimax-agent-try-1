"""Example 04 — LongTermMemory + ObsidianSync: add a fact and export to a vault.

`LongTermMemory` is a SQLite-backed key-value fact store
(`hello_agent.memory.long_term`). `ObsidianSync` writes those facts to
your Obsidian vault as markdown files with YAML frontmatter (see
`docs/ENGINEERING.md` §7.3).

Real usage (needs `OBSIDIAN_VAULT_PATH` set):

    $env:OBSIDIAN_VAULT_PATH = "D:\\path\\to\\my\\vault"
    uv run python examples/04_obsidian_export.py

Self-test (no env config, uses a temp vault):

    uv run python examples/04_obsidian_export.py --self-test

In self-test mode we override the `obsidian_vault_path` config to a
temp directory so the vault write actually happens to disk — we just
clean it up at the end.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _run_self_test() -> int:
    """Offline smoke — temp vault, temp db, write one fact + export it."""
    import gc

    from hello_agent.memory.long_term import LongTermMemory
    from hello_agent.memory.obsidian_sync import ObsidianSync

    tmp = tempfile.mkdtemp(prefix="hello_agent_ex04_")
    tmp_path = Path(tmp)
    # Windows quirk: `tempfile.mkdtemp` may return a path under
    # `%USERPROFILE%` that resolves to a different spelling (junction /
    # reparse point — e.g. `.mavis` → `.minimax`). Always `.resolve()` the
    # vault path BEFORE handing it to ObsidianSync so the relative_to() at
    # the end of the smoke uses the same spelling ObsidianSync wrote to.
    vault = (tmp_path / "vault").resolve()
    db_path = tmp_path / "memory" / "long_term.db"

    try:
        # Pass both paths explicitly so we don't have to mutate config.
        mem = LongTermMemory(db_path=db_path)
        sync = ObsidianSync(vault_path=vault)

        # 1. add_fact → 2. export_memory → file lands under vault/memory/.
        fact_key = "favorite_editor"
        fact_value = "vscode"
        fact_source = "example_04_self_test"
        mem.set_fact(fact_key, fact_value, source=fact_source)
        content = (
            f"My favorite editor is [[{fact_value}]] #editor #preference\n"
            f"Captured during the hello-agent-2 examples smoke test."
        )
        raw_path = sync.export_memory(
            memory_id=fact_key,
            content=content,
            kind="fact",
            title="Favorite editor",
            tags=["editor", "preference"],
        )
        # ObsidianSync may return a path that points through a junction
        # (Windows quirk — `tempfile.mkdtemp` on `%USERPROFILE%` can resolve
        # `.mavis` as `.minimax`, etc.). Resolve both sides before the
        # exists() check + the relative_to() comparison below.
        path = Path(raw_path).resolve() if raw_path is not None else None
        assert path is not None, "export_memory returned None — vault path didn't take"
        assert path.exists(), f"exported memory file missing: {path}"

        # 3. list_memories should see it.
        listed = sync.list_memories()
        ids = [m["id"] for m in listed]
        assert fact_key in ids, f"list_memories() did not return {fact_key}: {ids}"

        # 4. get_memory should return the full record.
        record = sync.get_memory(fact_key)
        assert record is not None
        assert "vscode" in record["content"]
        assert record["frontmatter"]["id"] == fact_key
        assert record["frontmatter"]["kind"] == "fact"
        assert "editor" in record["frontmatter"]["tags"]

        # Explicit close + GC sweep — SQLite WAL/SHM files on Windows hold
        # their lock until the connection is released AND the GC has run.
        mem.close()
        del mem
        gc.collect()

        # Show what landed on disk.
        rel = path.relative_to(vault)
        print(f"[self-test] OK: wrote memory to vault/{rel}")
        print(f"[self-test] OK: list_memories() saw {len(listed)} file(s): {ids}")
        return 0
    finally:
        # Best-effort cleanup. On Windows the SQLite WAL files can briefly
        # resist deletion; ignore_errors is fine because the OS will reap
        # the tempdir eventually.
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


def _run_live() -> int:
    """Real flow: requires OBSIDIAN_VAULT_PATH (or config.memory.obsidian_vault_path)."""
    from hello_agent.memory.long_term import LongTermMemory
    from hello_agent.memory.obsidian_sync import ObsidianSync

    mem = LongTermMemory()
    sync = ObsidianSync()
    if not sync.is_configured():
        print(
            "error: OBSIDIAN_VAULT_PATH is not set. Configure it in .env or "
            "config.yaml, then re-run. (See --self-test for an offline demo.)",
            file=sys.stderr,
        )
        return 1

    key = input("fact key: ").strip()
    value = input("fact value: ").strip()
    if not key or not value:
        print("error: key and value must be non-empty", file=sys.stderr)
        return 1

    mem.set_fact(key, value, source="example_04")
    path = sync.export_memory(
        memory_id=key,
        content=f"{key}: {value}",
        kind="fact",
        title=key.replace("_", " ").title(),
    )
    if path is None:
        print("(export_memory returned None; vault not configured)", file=sys.stderr)
        return 1
    print(f"wrote: {path}")
    mem.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LongTermMemory + ObsidianSync end-to-end.")
    parser.add_argument("--self-test", action="store_true", help="Offline smoke; uses a temp vault")
    args = parser.parse_args(argv)
    try:
        return _run_self_test() if args.self_test else _run_live()
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())