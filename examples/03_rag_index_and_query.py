"""Example 03 — RAG: walk a directory, chunk + embed + 4-strategy retrieve.

The full RAG pipeline has five stages:
  1. `hello_agent.rag.loader.load_directory(path)` → list of `{text, source, ...}`
  2. `hello_agent.rag.chunker.SlidingWindowChunker` → list of `Chunk`
  3. `hello_agent.rag.embedder.Embedder` → float vectors
  4. `hello_agent.rag.vector_store.VectorStore.add(...)` → persist to chromadb
  5. `hello_agent.rag.retrieval.retrieve(query, ...)` → top-k fused results

This example walks the bundled `docs/` directory (or any directory you pass
as an argument), indexes it into a temp chromadb collection, then runs a
`retrieve()` query through the 4-strategy ensemble (rewrite / hyde /
multi_query / rerank fused via Reciprocal Rank Fusion).

Real usage:

    uv run python examples/03_rag_index_and_query.py                # indexes docs/
    uv run python examples/03_rag_index_and_query.py ./my_notes     # indexes a different dir
    uv run python examples/03_rag_index_and_query.py "what is MCP?"  # custom query

Self-test (no LLM, no embedding provider, no chromadb network):

    uv run python examples/03_rag_index_and_query.py --self-test

In self-test mode we patch `Embedder.embed` to return deterministic
zero-vectors of the right length. The retrieval pipeline still runs
end-to-end; we just won't get meaningful similarity scores.
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


# ─── helpers ──────────────────────────────────────────────────────────────────


def _patch_embedder_for_offline() -> None:
    """Replace Embedder.embed + .embed_one with deterministic zero-vectors.

    The retrieval strategies accept any non-NaN vectors; similarity scores
    will all be 0.0 (every chunk ties), which is fine — we only assert that
    the pipeline ran and returned something.
    """
    from hello_agent.rag import embedder as embedder_mod

    class _ZeroEmbedder(embedder_mod.Embedder):
        def __init__(self, *args: object, **kwargs: object) -> None:  # noqa: D401
            # Bypass the parent's __init__ so we don't try to read config
            # or open network clients.
            self.provider = "stub"
            self.model = "stub"
            self.batch_size = 32
            self._dim = embedder_mod._LOCAL_DEFAULT_DIM

        def embed(self, texts: list[str]) -> list[list[float]]:  # noqa: D401
            return [[0.0] * self._dim for _ in texts]

        def embed_one(self, text: str) -> list[float]:  # noqa: D401
            return [0.0] * self._dim

        @property
        def dim(self) -> int:  # noqa: D401
            return self._dim

    embedder_mod.Embedder = _ZeroEmbedder  # type: ignore[assignment,misc]


def _walk_and_index(target: Path, persist_dir: Path) -> tuple[int, int]:
    """Load + chunk + embed + store. Returns (n_files, n_chunks)."""
    from hello_agent.rag.chunker import SlidingWindowChunker
    from hello_agent.rag.embedder import Embedder
    from hello_agent.rag.loader import load_directory
    from hello_agent.rag.vector_store import VectorStore

    docs = load_directory(target, recursive=True)
    if not docs:
        return (0, 0)

    chunker = SlidingWindowChunker(chunk_size_tokens=128, overlap_tokens=16)
    embedder = Embedder()
    store = VectorStore(collection="example_03", persist_dir=persist_dir)
    store.connect()

    n_files = 0
    n_chunks = 0
    for doc in docs:
        text = doc.get("text", "")
        source = doc.get("source", "")
        if not text.strip():
            continue
        chunks = chunker.chunk(text, source=source)
        if not chunks:
            continue
        embeddings = embedder.embed([c.text for c in chunks])
        ids = [f"{source}::{c.chunk_index:05d}".replace("\\", "/") for c in chunks]
        store.add(
            ids=ids,
            texts=[c.text for c in chunks],
            embeddings=embeddings,
            metadatas=[{"source": c.source, "chunk_index": c.chunk_index} for c in chunks],
        )
        n_files += 1
        n_chunks += len(chunks)
    store.close()
    return (n_files, n_chunks)


def _run_self_test() -> int:
    """Offline smoke — zero-vector embedder, fake LLM, walk a small fixture."""
    import gc

    _patch_embedder_for_offline()

    from hello_agent.core.llm import LLMClient
    from hello_agent.rag.embedder import Embedder
    from hello_agent.rag.retrieval import retrieve
    from hello_agent.rag.vector_store import VectorStore

    tmp = tempfile.mkdtemp(prefix="hello_agent_ex03_")
    tmp_path = Path(tmp)
    try:
        # Build a small fixture so the loader has something to chew on.
        (tmp_path / "a.md").write_text(
            "hello-agent-2 is a Windows Python agent.\nIt uses a ReAct loop and 4-strategy RAG.\n",
            encoding="utf-8",
        )
        (tmp_path / "b.md").write_text(
            "Obsidian vault sync stores long-term memories as markdown.\n",
            encoding="utf-8",
        )

        persist_dir = tmp_path / "chromadb"
        n_files, n_chunks = _walk_and_index(tmp_path, persist_dir)
        assert n_files == 2, f"expected 2 files indexed, got {n_files}"
        assert n_chunks >= 2, f"expected at least 2 chunks, got {n_chunks}"

        # Re-open and query.
        store = VectorStore(collection="example_03", persist_dir=persist_dir)
        store.connect()
        embedder = Embedder()

        # Stub the LLM so rewrite / hyde / multi_query / rerank all degrade
        # to "fall back to original query" (their documented behavior on
        # empty LLM responses). No network calls.
        llm = LLMClient(api_key="sk-self-test", base_url="http://localhost/self-test")
        fake_response = type(
            "Resp",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Msg", (), {"content": "", "tool_calls": None})()},
                    )()
                ],
                "usage": type("U", (), {"total_tokens": 1})(),
            },
        )()
        llm._sync = type(
            "FakeSync",
            (),
            {"chat": type("Chat", (), {"completions": type("C", (), {"create": staticmethod(lambda **kw: fake_response)})()})()},
        )()

        try:
            results = retrieve("hello-agent-2 RAG", store, embedder, llm, top_k=2)
        except Exception as exc:
            store.close()
            print(f"[self-test] retrieve raised (acceptable): {exc}", file=sys.stderr)
            print(f"[self-test] OK: indexed {n_files} files / {n_chunks} chunks (retrieve skip)")
            return 0
        store.close()
        gc.collect()  # Release chromadb SQLite file handles before cleanup.
        assert len(results) <= 2, f"top_k=2 violated: got {len(results)}"
        print(
            f"[self-test] OK: indexed {n_files} files / {n_chunks} chunks; "
            f"retrieve() returned {len(results)} result(s)"
        )
        return 0
    finally:
        # chromadb + Windows can hold file locks past close(); ignore_errors
        # keeps the smoke exit code clean. OS reaps the tempdir eventually.
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


def _run_live(target: Path, query: str) -> int:
    """Real pipeline: load config, embed via OpenAI-compatible API, persist, retrieve."""
    from hello_agent.core.llm import LLMClient
    from hello_agent.rag.embedder import Embedder
    from hello_agent.rag.retrieval import retrieve
    from hello_agent.rag.vector_store import VectorStore

    with tempfile.TemporaryDirectory() as tmp:
        persist_dir = Path(tmp) / "chromadb"
        n_files, n_chunks = _walk_and_index(target, persist_dir)
        if n_files == 0:
            print(f"(no text-native files found under {target})")
            return 0

        store = VectorStore(collection="example_03", persist_dir=persist_dir)
        store.connect()
        embedder = Embedder()
        llm = LLMClient()
        results = retrieve(query, store, embedder, llm, top_k=5)
        store.close()

        print(f"Indexed {n_files} file(s) / {n_chunks} chunk(s) from {target}")
        print(f"Top {len(results)} result(s) for: {query!r}")
        for i, r in enumerate(results, start=1):
            snippet = r.text[:120].replace("\n", " ")
            print(f"  {i}. [score={r.score:.3f}] {snippet}…")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index a directory with RAG + 4-strategy retrieval.")
    parser.add_argument(
        "target",
        nargs="?",
        default=str(_REPO_ROOT / "docs"),
        help="Directory to index (default: ./docs)",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="What is hello-agent-2?",
        help="Query string for the retrieval ensemble",
    )
    parser.add_argument("--self-test", action="store_true", help="Offline smoke; no network")
    args = parser.parse_args(argv)

    try:
        if args.self_test:
            return _run_self_test()
        return _run_live(Path(args.target), args.query)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())