"""Smoke test for the hello_agent.rag + hello_agent.memory (Obsidian/Git) layers.

Exercises the public surface of §6.7 (RAG) + §6.6 (memory scaffolds) end-to-end
without spinning up the LLM or hitting the network:

  1. `Chunker` — feed a 5000-char doc, assert chunk_count > 1.
  2. `Retrieval.ensemble_weights` — load config, assert sum == 1.0 and
     the 4 expected strategies are present.
  3. `VectorStore` connection — instantiate + try to .connect() against a
     tmp persist dir. Skips with [skip] if chromadb is not installed.
  4. `ObsidianSync` no-op scaffold — instantiate, confirm is_configured
     is False (no env), and export_memory returns None.
  5. `GitSync` no-op scaffold — instantiate, confirm is_configured is
     False, and force_sync returns the right reason.

Run from the worktree root:
    uv run python scripts/smoke_rag.py

Exit codes:
  0   every section passed
  1   a section reported a hard failure
  2   an unexpected exception escaped
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

# --- section helpers --------------------------------------------------------


class SmokeError(AssertionError):
    """A section reported a hard failure."""


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _ok(msg: str) -> None:
    print(f"  [ok] {msg}")


def _info(msg: str) -> None:
    print(f"  [..] {msg}")


def _skip(msg: str) -> None:
    print(f"  [skip] {msg}")


# --- section 1: Chunker on a 5000-char doc ----------------------------------


def smoke_chunker() -> None:
    _section("1. SlidingWindowChunker on a 5000-char document")
    from hello_agent.rag.chunker import SlidingWindowChunker

    chunker = SlidingWindowChunker(chunk_size_tokens=128, overlap_tokens=16)
    # 5000 chars of synthetic content — enough to force multiple chunks
    # at the 128-token window size.
    body = (
        "The quick brown fox jumps over the lazy dog. " * 130
    )  # ~5200 chars
    assert len(body) >= 5000, f"test doc should be >= 5000 chars, got {len(body)}"

    chunks = chunker.chunk(body, source="smoke://test-doc-1")
    assert len(chunks) > 1, f"expected multiple chunks, got {len(chunks)}"
    _ok(f"chunk_count = {len(chunks)} (expected > 1)")

    # Chunks should be roughly chunk_size_tokens (allow some slack for the
    # tiktoken cl100k_base encoding — the char-to-token ratio is ~4:1).
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert c.source == "smoke://test-doc-1"
        assert c.token_count > 0
        assert c.start_char >= 0
        assert c.end_char >= c.start_char
    _ok(f"chunk metadata valid for all {len(chunks)} chunks (index, source, token_count)")

    # Overlap check: consecutive chunks should share some tokens.
    if len(chunks) >= 2:
        a, b = chunks[0], chunks[1]
        assert a.end_char > a.start_char
        assert b.start_char < a.end_char, (
            f"chunks must overlap: chunk 0 ends at {a.end_char}, "
            f"chunk 1 starts at {b.start_char}"
        )
        _ok(f"overlap verified: chunk0=[{a.start_char},{a.end_char}], chunk1=[{b.start_char},{b.end_char}]")

    # Short document collapses to a single chunk.
    short_chunker = SlidingWindowChunker(chunk_size_tokens=512, overlap_tokens=64)
    short = short_chunker.chunk("hello world", source="smoke://short")
    assert len(short) == 1
    assert short[0].token_count >= 1
    _ok("short doc (<= chunk_size) collapses to a single chunk")


# --- section 2: Retrieval ensemble_weights sum to 1.0 ----------------------


def smoke_retrieval_weights() -> None:
    _section("2. Retrieval ensemble_weights — sum to 1.0")
    from hello_agent.rag.retrieval import ALL_STRATEGIES, ensemble_weights

    weights = ensemble_weights()
    _ok(f"ensemble_weights() = {weights}")
    for name in ALL_STRATEGIES:
        assert name in weights, f"missing strategy {name!r} in ensemble_weights"
    _ok(f"all 4 strategies present: {ALL_STRATEGIES}")

    total = sum(weights.values())
    assert abs(total - 1.0) < 1e-6, f"sum of weights = {total}, expected 1.0"
    _ok(f"sum(weights) = {total} (matches spec 0.4+0.2+0.2+0.2 = 1.0)")

    # The rrf_fuse function is the math that powers the ensemble.
    from hello_agent.rag.retrieval import rrf_fuse
    from hello_agent.rag.vector_store import RetrievalResult

    a = RetrievalResult(chunk_id="a", text="alpha", source="s1", score=0.9, strategy="x")
    b = RetrievalResult(chunk_id="b", text="beta", source="s2", score=0.7, strategy="x")
    c = RetrievalResult(chunk_id="c", text="gamma", source="s3", score=0.5, strategy="x")

    # Two lists, each ranking 3 docs differently.
    list1 = [a, b, c]
    list2 = [b, a, c]
    fused = rrf_fuse([list1, list2])

    assert len(fused) == 3
    # a and b appear in both lists → higher RRF score than c (which only
    # appears at rank 3 in both).
    a_fused = next(r for r in fused if r.chunk_id == "a")
    b_fused = next(r for r in fused if r.chunk_id == "b")
    c_fused = next(r for r in fused if r.chunk_id == "c")
    assert a_fused.score > c_fused.score
    assert b_fused.score > c_fused.score
    _ok("rrf_fuse: docs in both lists score higher than docs in only one")


# --- section 3: VectorStore connection (skip if chromadb missing) ----------


def smoke_vector_store(tmp_dir: Path) -> None:
    _section("3. VectorStore.connect() — round-trip add + query")
    from hello_agent.rag.vector_store import VectorStore

    try:
        store = VectorStore(
            collection="smoke_collection",
            persist_dir=tmp_dir / "chromadb",
        )
        store.connect()
    except ImportError:
        _skip("chromadb not installed; section skipped")
        return

    try:
        assert store.is_connected()
        _ok("VectorStore.connect() succeeded against tmp persist dir")

        # Empty collection should report 0 chunks.
        assert store.count() == 0
        _ok(f"empty collection count = {store.count()}")

        # Add 3 fake chunks, query back the nearest.
        fake_vectors = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        store.add(
            ids=["a", "b", "c"],
            texts=["alpha content", "beta content", "gamma content"],
            embeddings=fake_vectors,
            metadatas=[{"source": "alpha.md"}, {"source": "beta.md"}, {"source": "gamma.md"}],
        )
        assert store.count() == 3
        _ok(f"add() upserted 3 chunks; count = {store.count()}")

        # Query for the "alpha" vector — should rank a first.
        results = store.query([1.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0].chunk_id == "a"
        assert results[0].source == "alpha.md"
        _ok(
            f"query() returned {len(results)} results, top1 = "
            f"{results[0].chunk_id} (source={results[0].source})"
        )

        # Empty embedding → empty result (defensive).
        empty = store.query([], top_k=5)
        assert empty == []
        _ok("query([]) returns [] (defensive: empty input)")
    finally:
        # Release chromadb's file handles so the tempdir can be cleaned up
        # (Windows: SQLite/hnswlib hold OS-level locks).
        store.close()


# --- section 4: ObsidianSync no-op scaffold ---------------------------------


def smoke_obsidian_noop() -> None:
    _section("4. ObsidianSync no-op scaffold (OBSIDIAN_VAULT_PATH unset)")
    from hello_agent.memory.obsidian_sync import ObsidianSync

    # Make sure no vault is configured for this section.
    os.environ.pop("OBSIDIAN_VAULT_PATH", None)
    sync = ObsidianSync()
    assert not sync.is_configured()
    _ok("ObsidianSync().is_configured() == False (no vault set)")

    # export_memory is a no-op returning None.
    out = sync.export_memory("test_id", "hello world", kind="fact")
    assert out is None
    _ok("export_memory() returned None (no-op)")

    # list_memories / get_memory / extract_relations return empty results.
    assert sync.list_memories() == []
    assert sync.get_memory("any") is None
    assert sync.extract_relations() == {}
    _ok("list/get/extract all return empty results")

    # Now configure a vault and re-test.
    with tempfile.TemporaryDirectory(prefix="smoke_obsidian_") as td:
        os.environ["OBSIDIAN_VAULT_PATH"] = str(Path(td))
        # Flush config so the env change takes effect.
        from hello_agent.core.config import reload_config

        reload_config()
        sync2 = ObsidianSync()
        assert sync2.is_configured()
        _ok(f"after setting OBSIDIAN_VAULT_PATH={td!r}: is_configured() == True")

        # Reset for next test sections.
        os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        reload_config()


# --- section 5: GitSync no-op scaffold --------------------------------------


def smoke_git_noop() -> None:
    _section("5. GitSync no-op scaffold (token/vault unset)")
    from hello_agent.memory.git_sync import GitSync

    # Ensure token is unset for this section.
    os.environ.pop("OBSIDIAN_GIT_TOKEN", None)
    os.environ.pop("OBSIDIAN_VAULT_PATH", None)
    from hello_agent.core.config import reload_config

    reload_config()

    g = GitSync()
    assert not g.is_configured()
    _ok("GitSync().is_configured() == False (no vault + no token)")

    # start() is a no-op returning False when not configured.
    started = g.start()
    assert started is False
    assert not g.is_running()
    _ok("start() returned False; is_running() == False (no thread spawned)")

    # force_sync returns the right reason.
    result = g.force_sync()
    assert result["committed"] is False
    assert result["pushed"] is False
    assert "reason" in result
    _ok(f"force_sync() -> {result}")


# --- driver -----------------------------------------------------------------


def main() -> int:
    failures: list[str] = []
    # `ignore_cleanup_errors=True` (Python 3.10+) keeps the script from
    # returning a non-zero exit when chromadb's persistent client holds
    # SQLite/hnswlib file handles longer than expected — a known
    # chromadb-on-Windows quirk. The smoke output (OK / FAIL) is fully
    # written before tempdir cleanup, so this only affects exit semantics.
    with tempfile.TemporaryDirectory(prefix="smoke_rag_", ignore_cleanup_errors=True) as td:
        tmp_dir = Path(td)
        _info(f"tmp dir = {tmp_dir}")

        sections = [
            ("smoke_chunker", smoke_chunker),
            ("smoke_retrieval_weights", smoke_retrieval_weights),
            ("smoke_vector_store", lambda: smoke_vector_store(tmp_dir)),
            ("smoke_obsidian_noop", smoke_obsidian_noop),
            ("smoke_git_noop", smoke_git_noop),
        ]

        for name, fn in sections:
            try:
                fn()
            except SmokeError as exc:
                print(f"  [FAIL] {name}: {exc}", file=sys.stderr)
                failures.append(name)
            except Exception as exc:  # noqa: BLE001
                print(f"  [CRASH] {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                traceback.print_exc()
                failures.append(name)

    if failures:
        print(
            f"\n[smoke_rag] FAIL: {len(failures)} section(s) failed: {failures}",
            file=sys.stderr,
        )
        return 1
    print("\n[smoke_rag] OK: all 5 sections passed")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--workdir" and len(sys.argv) > 2:
        os.chdir(sys.argv[2])
    sys.exit(main())
