"""chromadb wrapper for the RAG pipeline.

Implements the spec from ENGINEERING.md §7.2.4 (vector_store part):
  - persistent client at `CHROMADB_PERSIST_DIR` (resolved from config)
  - one collection per source path / index name
  - API: `add(chunks, embeddings)`, `query(emb, top_k)`, `delete(ids)`, `count()`

chromadb is an *optional* dependency (`pip install chromadb` or
`uv sync --extra chromadb`). We import it lazily inside `__init__` and
on every method that needs it, so a fresh install can still run
`hello-agent doctor` etc. without the heavy chromadb stack.

`RetrievalResult` is the cross-strategy return type — it lives here (not
in retrieval.py) because both modules produce it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hello_agent.core.config import get_config
from hello_agent.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RetrievalResult:
    """A single ranked chunk returned by a retrieval strategy.

    Used by all 4 strategies in `retrieval.py` and the final fused result.
    `score` is a float in [0, 1] (chromadb returns cosine distance
    inverted) or an RRF score (any positive number) depending on the caller.
    `metadata` carries strategy-specific extras (e.g. `llm_rerank_score`).
    """

    chunk_id: str
    text: str
    source: str
    score: float
    strategy: str
    metadata: dict = field(default_factory=dict)


class VectorStore:
    """A thin, typed wrapper around a single chromadb collection.

    Args:
        collection: collection name (e.g. "docs" or a per-source-path name).
        persist_dir: override the `CHROMADB_PERSIST_DIR` from config. If a
            relative path, it's anchored at `$HELLO_AGENT_HOME`.

    The collection is auto-created on first `add()`. `query()` returns a
    list of `RetrievalResult`, ranked by chromadb's cosine similarity
    (higher is better — we invert chromadb's `distance` to `score`).
    """

    DEFAULT_COLLECTION = "hello_agent_docs"

    def __init__(
        self,
        collection: str = DEFAULT_COLLECTION,
        persist_dir: str | Path | None = None,
    ) -> None:
        self.collection_name: str = collection
        self.persist_dir: Path = self._resolve_persist_dir(persist_dir)
        # Lazy handles — created on first .connect() or .add().
        self._client: Any | None = None
        self._collection: Any | None = None

    # --- public API -------------------------------------------------------

    def connect(self) -> None:
        """Open the chromadb client + collection. Idempotent."""
        if self._client is not None:
            return
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "chromadb is not installed. Install with: "
                "`uv sync --extra chromadb`"
            ) from exc
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        # PersistentClient survives process restarts. We disable the
        # default telemetry + anonymized-chromadb to keep logs clean.
        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False, allow_reset=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.bind(category="rag").info(
            "VectorStore connected: collection={} persist_dir={}",
            self.collection_name,
            self.persist_dir,
        )

    def is_connected(self) -> bool:
        return self._client is not None and self._collection is not None

    def add(
        self,
        *,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict] | None = None,
    ) -> None:
        """Add (or upsert) chunks + their embeddings into the collection.

        Lengths of `ids`, `texts`, `embeddings` (and optional `metadatas`)
        must all match. Empty input is a no-op.
        """
        if not ids:
            return
        if not (len(ids) == len(texts) == len(embeddings)):
            raise ValueError(
                f"ids/texts/embeddings length mismatch: "
                f"{len(ids)}/{len(texts)}/{len(embeddings)}"
            )
        if metadatas is not None and len(metadatas) != len(ids):
            raise ValueError(
                f"metadatas length {len(metadatas)} != ids length {len(ids)}"
            )
        if metadatas is None:
            metadatas = [{} for _ in ids]
        self.connect()
        # chromadb's upsert handles both insert and update on the same id.
        self._collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(
        self,
        embedding: list[float],
        *,
        top_k: int = 8,
        where: dict | None = None,
    ) -> list[RetrievalResult]:
        """Return the top-k chunks nearest to `embedding`.

        Each result has `score = 1.0 - distance` (cosine similarity, so
        higher = better). When the collection is empty, returns an empty
        list — never raises.
        """
        if not embedding:
            return []
        self.connect()
        if self.count() == 0:
            return []
        k = min(int(top_k), self.count())
        res = self._collection.query(
            query_embeddings=[embedding],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out: list[RetrievalResult] = []
        for cid, doc, meta, dist in zip(ids, docs, metas, dists, strict=False):
            meta = meta or {}
            source = str(meta.get("source", ""))
            out.append(
                RetrievalResult(
                    chunk_id=str(cid),
                    text=str(doc),
                    source=source,
                    score=self._distance_to_score(dist),
                    strategy="vector",
                    metadata=dict(meta),
                )
            )
        return out

    def delete(self, ids: list[str]) -> None:
        """Remove chunks by id. No-op if `ids` is empty or chromadb missing."""
        if not ids:
            return
        self.connect()
        self._collection.delete(ids=ids)

    def count(self) -> int:
        """Total number of chunks in the collection. Returns 0 if not connected."""
        if self._collection is None:
            return 0
        try:
            return int(self._collection.count())
        except Exception:  # noqa: BLE001 — collection not yet created
            return 0

    def reset(self) -> None:
        """Drop the entire collection. Mostly for tests."""
        if self._collection is None:
            return
        try:
            self._client.delete_collection(self.collection_name)
        except Exception:  # noqa: BLE001
            pass
        self._collection = None

    def close(self) -> None:
        """Release chromadb's file handles (notably important on Windows).

        chromadb's PersistentClient keeps SQLite / hnswlib file handles
        open; on Windows the OS won't let us delete the persist dir until
        those handles are released. Tests and smoke scripts should call
        this before any tempdir cleanup.
        """
        if self._client is None:
            return
        try:
            # Best-effort — chromadb may not expose a public close().
            close_fn = getattr(self._client, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:  # noqa: BLE001
            pass
        self._client = None
        self._collection = None

    def __enter__(self) -> VectorStore:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- internals --------------------------------------------------------

    def _resolve_persist_dir(self, override: str | Path | None) -> Path:
        if override is not None:
            p = Path(override).expanduser()
            if not p.is_absolute():
                from hello_agent.core.paths import get_hello_agent_home
                p = get_hello_agent_home() / p
            return p.resolve()
        cfg_path = get_config().rag.chromadb_persist_dir
        p = Path(cfg_path).expanduser()
        if not p.is_absolute():
            from hello_agent.core.paths import get_hello_agent_home
            p = get_hello_agent_home() / p
        return p.resolve()

    @staticmethod
    def _distance_to_score(distance: float) -> float:
        """Convert a chromadb cosine distance into a [0, 1] similarity score.

        chromadb's cosine distance is in [0, 2] (0 = identical, 2 = opposite).
        We map to a similarity-like score in [0, 1] via `1 - dist/2`.
        """
        try:
            d = float(distance)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, 1.0 - d / 2.0))
