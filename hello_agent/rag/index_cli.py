"""`hello-agent rag index|query` — index and query a RAG corpus.

This module is the library side of the `cli/rag.py` Typer commands:

  - `run_index(path, recursive=True)` walks a directory, chunks + embeds
    + stores the result, and returns `(n_files, n_chunks)`.

  - `run_query(text, top_k=8, strategies=None)` runs the 4-strategy
    retrieval pipeline and returns a list of `RetrievalResult`.

The Typer wrapper in `cli/rag.py` is responsible for printing; this
module is the testable library surface.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from hello_agent.core.logging import get_logger
from hello_agent.core.types import Message, Role
from hello_agent.rag.chunker import Chunk, SlidingWindowChunker
from hello_agent.rag.embedder import Embedder
from hello_agent.rag.loader import load_directory
from hello_agent.rag.retrieval import ALL_STRATEGIES, retrieve
from hello_agent.rag.vector_store import RetrievalResult, VectorStore

logger = get_logger(__name__)


def _make_chunk_id(source: str, chunk_index: int) -> str:
    """Stable, deterministic chunk id — `source::chunk_index`.

    Sources are absolute paths in practice, so collisions across docs
    don't happen (the same source always has unique chunk_index values).
    """
    # Strip Windows drive / backslash weirdness for cross-platform safety.
    safe_source = source.replace("\\", "/")
    return f"{safe_source}::{chunk_index:05d}"


def run_index(
    path: str | Path,
    *,
    recursive: bool = True,
    collection: str = VectorStore.DEFAULT_COLLECTION,
    persist_dir: str | Path | None = None,
    extensions: list[str] | None = None,
) -> tuple[int, int]:
    """Walk a directory, chunk + embed + store. Returns (n_files, n_chunks).

    `n_files` counts the files that produced at least one chunk. Files
    that error out or produce empty text are skipped (with a warning).

    The collection is upserted — re-running the command updates existing
    chunks with new embeddings (useful for incremental rebuilds).
    """
    docs = load_directory(path, recursive=recursive, extensions=extensions)
    logger.bind(category="rag").info(
        "run_index: {} files loaded from {}", len(docs), path
    )
    if not docs:
        return (0, 0)

    chunker = SlidingWindowChunker()
    embedder = Embedder()
    store = VectorStore(collection=collection, persist_dir=persist_dir)
    store.connect()

    n_files_indexed = 0
    n_chunks_indexed = 0

    for doc in docs:
        text = doc.get("text", "")
        source = doc.get("source", "")
        if not text.strip():
            logger.bind(category="rag").debug(
                "skipping empty doc: {}", source
            )
            continue
        chunks: list[Chunk] = chunker.chunk(text, source=source)
        if not chunks:
            continue
        embeddings = embedder.embed([c.text for c in chunks])
        ids = [_make_chunk_id(c.source, c.chunk_index) for c in chunks]
        metadatas = [
            {
                "source": c.source,
                "chunk_index": c.chunk_index,
                "token_count": c.token_count,
                "start_char": c.start_char,
                "end_char": c.end_char,
                "loader": doc.get("loader", "text"),
            }
            for c in chunks
        ]
        store.add(
            ids=ids,
            texts=[c.text for c in chunks],
            embeddings=embeddings,
            metadatas=metadatas,
        )
        n_files_indexed += 1
        n_chunks_indexed += len(chunks)

    logger.bind(category="rag").info(
        "run_index: indexed {} files, {} chunks (collection={})",
        n_files_indexed,
        n_chunks_indexed,
        collection,
    )
    return (n_files_indexed, n_chunks_indexed)


def run_query(
    text: str,
    *,
    top_k: int = 8,
    strategies: list[str] | None = None,
    collection: str = VectorStore.DEFAULT_COLLECTION,
    persist_dir: str | Path | None = None,
) -> list[RetrievalResult]:
    """Run the 4-strategy retrieval pipeline and return top-k results.

    Strategies default to all 4 from config (`rewrite`, `hyde`,
    `multi_query`, `rerank`).
    """
    from hello_agent.core.llm import LLMClient

    store = VectorStore(collection=collection, persist_dir=persist_dir)
    embedder = Embedder()
    llm = LLMClient()
    strat_list = strategies or list(ALL_STRATEGIES)
    return retrieve(
        text,
        store,
        embedder,
        llm,
        strategies=strat_list,
        top_k=top_k,
    )


# `cli/rag.py` may want a minimal "import this to verify the subsystem is
# importable" guard. This block lets the smoke test do a quick import-only
# check.
def _self_test() -> dict[str, Any]:
    """Cheap importability check. Returns a dict of subsystem status."""
    return {
        "loader": "ok",
        "chunker": "ok",
        "embedder": "ok",
        "vector_store": "ok",
        "retrieval": "ok",
    }


# `__all__` is the contract `cli/rag.py` and external tests rely on.
__all__ = [
    "run_index",
    "run_query",
    "ALL_STRATEGIES",
    "Message",  # re-export from core.types for convenience
    "Role",
    "Chunk",
    "RetrievalResult",
    "VectorStore",
    "Embedder",
    "SlidingWindowChunker",
]
