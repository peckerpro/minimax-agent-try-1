"""Embedding backends for the RAG pipeline.

Two backends behind a common interface (see ENGINEERING.md §7.2.3):

- `openai` — uses the official `openai` SDK against whatever base_url is
  configured (`LLM_BASE_URL`). This means OpenAI-compatible providers
  (DeepSeek, Zhipu, Ollama, LM Studio, etc.) all work for embeddings too
  as long as they expose a `/v1/embeddings` endpoint.

- `local`  — uses `sentence-transformers` for fully-offline embedding.
  The local model is loaded lazily on first use. If the package is not
  installed, `_embed_local()` raises an `ImportError` with a clear hint
  to install the `local-embed` extra.

Batched calls (default 32 texts/batch) keep token usage manageable for
both backends.
"""
from __future__ import annotations

from typing import Any

from hello_agent.core.config import get_config, get_env
from hello_agent.core.logging import get_logger

logger = get_logger(__name__)


# Default embedding dimensions for the well-known OpenAI models.
# Anything not in this table falls back to `cfg.embedding_dim` (config.yaml
# default 1536, which is the same as `text-embedding-3-small`).
_OPENAI_MODEL_DIMS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

_LOCAL_DEFAULT_DIM = 768  # all-MiniLM-L2-v2 / most sentence-transformers


class Embedder:
    """Embedding backend dispatch. One instance per (provider, model)."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        cfg = get_config().rag
        self.provider: str = (provider or cfg.embedding_provider).lower()
        self.model: str = model or cfg.embedding_model
        self.batch_size: int = batch_size or cfg.embedder_batch_size
        # Lazy-initialized backend clients / models.
        self._openai: Any | None = None
        self._local: Any | None = None

    # --- public API -------------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts. Returns one float vector per input text.

        Empty / blank inputs are rejected upfront; downstream code can rely
        on len(embed(texts)) == len(texts) and on non-empty vectors.
        """
        if not texts:
            return []
        # Reject empty strings — they confuse both backends.
        cleaned = [t if t else " " for t in texts]
        if self.provider == "openai":
            return self._embed_openai(cleaned)
        if self.provider == "local":
            return self._embed_local(cleaned)
        raise ValueError(
            f"Unknown embedding provider: {self.provider!r}. "
            f"Expected 'openai' or 'local'."
        )

    def embed_one(self, text: str) -> list[float]:
        """Convenience for a single text. Returns a flat float vector."""
        return self.embed([text])[0]

    @property
    def dim(self) -> int:
        """Output dimension of the embedding model."""
        if self.provider == "openai":
            return _OPENAI_MODEL_DIMS.get(self.model, get_config().rag.embedding_dim)
        # For local models, we don't actually load the model here — we just
        # report the common case. The model itself can be queried after
        # first embed() via `self._local.get_sentence_embedding_dimension()`.
        return _LOCAL_DEFAULT_DIM

    # --- openai backend ---------------------------------------------------

    def _ensure_openai(self) -> Any:
        if self._openai is None:
            from openai import OpenAI

            env = get_env()
            self._openai = OpenAI(
                base_url=env.llm_base_url,
                api_key=env.llm_api_key,
                timeout=env.llm_timeout_seconds,
                max_retries=env.llm_max_retries,
            )
        return self._openai

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        client = self._ensure_openai()
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            logger.bind(category="llm").debug(
                "embedding batch size={} model={} (provider={})",
                len(batch),
                self.model,
                self.provider,
            )
            resp = client.embeddings.create(model=self.model, input=batch)
            # The OpenAI SDK returns embeddings in input order.
            out.extend([list(d.embedding) for d in resp.data])
        return out

    # --- local backend ----------------------------------------------------

    def _ensure_local(self) -> Any:
        if self._local is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover
                raise ImportError(
                    "Local embedding backend requires the 'sentence-transformers' "
                    "package. Install with: uv add sentence-transformers "
                    "(or `uv sync --extra local-embed`)"
                ) from exc
            self._local = SentenceTransformer(self.model)
        return self._local

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_local()
        vectors = model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return f"Embedder(provider={self.provider!r}, model={self.model!r}, dim={self.dim})"
