"""4-strategy advanced retrieval (ENGINEERING.md §7.2.4).

Four strategies, each producing a ranked list of `RetrievalResult`s, then
fused via Reciprocal Rank Fusion (RRF) into a single ranking:

  1. `rewrite`    — LLM rewrites the query into N semantically equivalent
                    phrasings; embed each, retrieve, dedupe by chunk_id.
  2. `hyde`       — LLM writes a hypothetical answer (HyDE), embed *that*,
                    retrieve. Often finds relevant docs the original query
                    missed because the hypothetical lives in the same
                    embedding space as the actual documents.
  3. `multi_query`— LLM decomposes the query into N sub-questions, embed
                    each, retrieve, dedupe by chunk_id.
  4. `rerank`     — Take the fused candidate set so far, re-rank the top
                    N with an LLM 0–10 relevance score. Final score is
                    `0.6 * cosine + 0.4 * llm/10`. Graceful fallback if
                    the LLM returns non-JSON.

Public API:
  - `ensemble_weights()` → dict[str, float] from config
  - `rrf_fuse(lists, k)` → fused list
  - `retrieve(query, vector_store, embedder, llm, ...)` → top-k results

This module depends on `core.llm.LLMClient` and `rag.embedder.Embedder`.
The LLM-dependent strategies degrade gracefully: if the LLM call fails
or returns non-JSON, we fall back to the original query (so `retrieve()`
always returns *something*).
"""
from __future__ import annotations

import json
from collections import defaultdict

from hello_agent.core.config import get_config
from hello_agent.core.llm import LLMClient
from hello_agent.core.logging import get_logger
from hello_agent.core.types import Message, Role
from hello_agent.rag.embedder import Embedder
from hello_agent.rag.vector_store import RetrievalResult, VectorStore

logger = get_logger(__name__)


# Strategy names — must match the keys in `config.rag.retrieval.strategies`.
ALL_STRATEGIES = ("rewrite", "hyde", "multi_query", "rerank")


# ─── helpers -----------------------------------------------------------------


def ensemble_weights() -> dict[str, float]:
    """Read the per-strategy weights from config.

    Returns a dict of {strategy_name: weight}. Only strategies that are
    explicitly enabled in config are included.
    """
    cfg = get_config().rag.retrieval
    out: dict[str, float] = {}
    for name, sc in cfg.strategies.items():
        if sc.enabled:
            out[name] = float(sc.weight)
    return out


def rrf_fuse(
    ranked_lists: list[list[RetrievalResult]],
    k: int = 60,
) -> list[RetrievalResult]:
    """Combine multiple ranked lists via Reciprocal Rank Fusion.

    score(d) = sum( 1 / (k + rank_i(d)) ) for each list i, where rank_i(d)
    is the 1-based rank of d in list i. Larger k flattens the impact of
    rank-1 hits (k=60 is the standard RRF default from the original paper).
    """
    scores: dict[str, float] = defaultdict(float)
    by_id: dict[str, RetrievalResult] = {}
    for lst in ranked_lists:
        for rank, result in enumerate(lst, start=1):
            scores[result.chunk_id] += 1.0 / (k + rank)
            # First write wins for the chunk body / source (they're identical
            # across lists for the same chunk_id).
            if result.chunk_id not in by_id:
                by_id[result.chunk_id] = result
    fused = [
        RetrievalResult(
            chunk_id=cid,
            text=by_id[cid].text,
            source=by_id[cid].source,
            score=score,
            strategy="rrf_fused",
            metadata=dict(by_id[cid].metadata),
        )
        for cid, score in sorted(scores.items(), key=lambda kv: -kv[1])
    ]
    return fused


# ─── LLM helpers -------------------------------------------------------------


def _llm_chat_text(llm: LLMClient, user_prompt: str, *, temperature: float = 0.5) -> str:
    """Run a one-shot chat completion and return the assistant text.

    Returns "" on any failure (no LLM_API_KEY, network error, etc.) — the
    retrieval strategies treat empty string as "fall back to original query".
    """
    try:
        resp = llm.chat(
            messages=[Message(role=Role.USER, content=user_prompt)],
            temperature=temperature,
        )
    except Exception as exc:  # noqa: BLE001 — fall through to caller
        logger.debug("LLM call in retrieval failed: {}", exc)
        return ""
    try:
        return (resp.choices[0].message.content or "").strip()
    except (AttributeError, IndexError, KeyError):
        return ""


def _safe_json_list(text: str) -> list[str] | None:
    """Parse `text` as a JSON list of strings. Returns None on failure."""
    if not text:
        return None
    # Some models wrap their JSON in ```json ... ``` fences — strip them.
    s = text.strip()
    if s.startswith("```"):
        # Take the inner content between the first and last fence line.
        lines = s.splitlines()
        inner: list[str] = []
        in_block = False
        for ln in lines:
            if ln.strip().startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                inner.append(ln)
        s = "\n".join(inner).strip()
    try:
        data = json.loads(s)
    except (ValueError, TypeError):
        return None
    if isinstance(data, str):
        # Some models return a single string instead of a list.
        return [data]
    if isinstance(data, list):
        out: list[str] = []
        for item in data:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict) and "query" in item:
                out.append(str(item["query"]))
            else:
                out.append(str(item))
        return [x for x in out if x]
    return None


# ─── Strategy 1: Query Rewrite -----------------------------------------------


def query_rewrite(query: str, llm: LLMClient, n_rewrites: int = 3) -> list[str]:
    """Generate `n_rewrites` alternative phrasings of `query` + the original.

    The output is `[original, rewrite_1, rewrite_2, rewrite_3]`. On LLM
    failure, returns just `[original]`.
    """
    prompt = (
        f"Given the user's search query, generate {n_rewrites} alternative "
        f"phrasings that would retrieve the same information. Return a JSON "
        f"array of strings. Make the rephrasings diverse: use synonyms, "
        f"different angles, related concepts.\n\n"
        f"User query: {query!r}\n\nJSON array:"
    )
    raw = _llm_chat_text(llm, prompt, temperature=0.5)
    parsed = _safe_json_list(raw)
    if not parsed:
        return [query]
    return [query, *parsed[:n_rewrites]]


# ─── Strategy 2: HyDE --------------------------------------------------------


def hyde_generate(query: str, llm: LLMClient) -> str:
    """Generate a hypothetical document that would answer `query`.

    Returns the generated passage (no JSON wrapping). Empty string on failure.
    """
    prompt = (
        "Write a short passage (2-3 paragraphs) that would be a perfect answer "
        "to the following question. Don't hedge — write as if you know the answer.\n\n"
        f"Question: {query}\n\nPassage:"
    )
    return _llm_chat_text(llm, prompt, temperature=0.7)


# ─── Strategy 3: Multi-Query -------------------------------------------------


def multi_query(query: str, llm: LLMClient, n_queries: int = 4) -> list[str]:
    """Generate `n_queries` distinct sub-questions + the original.

    Returns `[original, q1, q2, q3, q4]`. On failure returns `[original]`.
    """
    prompt = (
        f"Break the following question into {n_queries} distinct sub-questions, "
        f"each of which could be answered by a different document. Return a JSON "
        f"array of strings.\n\n"
        f"Original question: {query!r}\n\nJSON array of sub-questions:"
    )
    raw = _llm_chat_text(llm, prompt, temperature=0.5)
    parsed = _safe_json_list(raw)
    if not parsed:
        return [query]
    return [query, *parsed[:n_queries]]


# ─── Strategy 4: Re-rank -----------------------------------------------------


def rerank(
    query: str,
    candidates: list[RetrievalResult],
    llm: LLMClient,
    *,
    top_n: int = 20,
) -> list[RetrievalResult]:
    """Re-rank the top-N candidates using a cheap LLM 0–10 relevance pass.

    Final score = `0.6 * original_cosine + 0.4 * (llm_score / 10)`. We only
    re-rank the top `top_n` candidates (cost control). The rest keep their
    original cosine score.

    On any LLM failure (no key, non-JSON, etc.), we silently fall back to
    the original cosine scores.
    """
    if len(candidates) <= 1:
        return candidates

    top = candidates[:top_n]
    rest = candidates[top_n:]

    items_text = "\n\n".join(
        f"[{i}] (similarity={c.score:.3f})\n{c.text[:500]}"
        for i, c in enumerate(top)
    )
    prompt = (
        "You are a relevance ranker. Score each document's relevance to the "
        "query on a 0-10 scale. Output a JSON array of integers, one per "
        "document, in the same order.\n\n"
        f"Query: {query!r}\n\nDocuments:\n{items_text}\n\nJSON array of scores:"
    )
    raw = _llm_chat_text(llm, prompt, temperature=0.0)
    scores = _safe_json_list(raw)
    if not scores:
        return candidates
    # The model may give us floats-as-strings; coerce carefully.
    coerced: list[float] = []
    for s in scores:
        try:
            coerced.append(max(0.0, min(10.0, float(s))))
        except (TypeError, ValueError):
            coerced.append(0.0)

    for c, s in zip(top, coerced, strict=False):
        c.score = 0.6 * c.score + 0.4 * (s / 10.0)
        c.metadata["llm_rerank_score"] = s

    top.sort(key=lambda c: c.score, reverse=True)
    return top + rest


# ─── Main entry: retrieve() --------------------------------------------------


def retrieve(
    query: str,
    vector_store: VectorStore,
    embedder: Embedder,
    llm: LLMClient,
    *,
    strategies: list[str] | None = None,
    top_k: int = 8,
    candidate_k: int | None = None,
) -> list[RetrievalResult]:
    """Run the 4 strategies and return the fused top-k results.

    Args:
        query:         The user query string.
        vector_store:  The chromadb-backed VectorStore (any backend that
                       implements the `query(emb, top_k)` protocol).
        embedder:      The Embedder instance.
        llm:           The LLMClient (used for rewrite / hyde / multi_query
                       / rerank prompts).
        strategies:    Subset of `[rewrite, hyde, multi_query, rerank]`.
                       Defaults to all enabled strategies in config.
        top_k:         How many results to return. Default 8 (matches
                       `config.rag.retrieval.final_top_k`).
        candidate_k:   How many candidates each strategy retrieves before
                       fusion. Default 20 (matches config).

    Returns:
        A list of `RetrievalResult`, sorted by fused score (descending),
        length == min(top_k, total_chunks).
    """
    cfg = get_config().rag.retrieval
    weights = ensemble_weights()
    enabled_strats = [s for s in (strategies or list(ALL_STRATEGIES)) if s in weights]
    if not enabled_strats:
        # No enabled strategies — fall back to a plain vector search.
        enabled_strats = ["rewrite"]
    cand_k = candidate_k or cfg.candidate_k

    ranked_lists: list[list[RetrievalResult]] = []

    if "rewrite" in enabled_strats:
        ranked_lists.append(
            _dedupe_collect(
                _embed_and_query_each(query_rewrite(query, llm), embedder, vector_store, cand_k)
            )
        )

    if "hyde" in enabled_strats:
        passage = hyde_generate(query, llm) or query
        emb = embedder.embed_one(passage)
        ranked_lists.append(vector_store.query(emb, top_k=cand_k))

    if "multi_query" in enabled_strats:
        ranked_lists.append(
            _dedupe_collect(
                _embed_and_query_each(multi_query(query, llm), embedder, vector_store, cand_k)
            )
        )

    # Re-rank must come last so it sees the fused-so-far top-N.
    if "rerank" in enabled_strats:
        base = rrf_fuse(ranked_lists)[:cand_k] if ranked_lists else _plain_fallback(
            query, embedder, vector_store, cand_k
        )
        # We re-rank the *fused* list (top-N by RRF) — gives a single
        # unified candidate pool rather than re-ranking per-strategy.
        top_n_for_rerank = cfg.strategies.get("rerank")
        if top_n_for_rerank is not None and top_n_for_rerank.top_n > 0:
            reranked = rerank(query, base, llm, top_n=top_n_for_rerank.top_n)
        else:
            reranked = base
        ranked_lists.append(reranked)

    if not ranked_lists:
        # No strategies at all (impossible in practice) — plain vector search.
        return _plain_fallback(query, embedder, vector_store, top_k)

    fused = rrf_fuse(ranked_lists)
    return fused[:top_k]


# ─── Internals ---------------------------------------------------------------


def _embed_and_query_each(
    queries: list[str],
    embedder: Embedder,
    vector_store: VectorStore,
    top_k: int,
) -> list[RetrievalResult]:
    """Embed each query, run vector_store.query, return the concatenation.

    Note: this can produce duplicates (same chunk retrieved by multiple
    rewrites). The caller dedupes.
    """
    if not queries:
        return []
    embeddings = embedder.embed(queries)
    out: list[RetrievalResult] = []
    for emb in embeddings:
        out.extend(vector_store.query(emb, top_k=top_k))
    return out


def _dedupe_collect(results: list[RetrievalResult]) -> list[RetrievalResult]:
    """Dedupe by `chunk_id`, keeping the highest score per id.

    Returns the deduped list sorted by score desc.
    """
    by_id: dict[str, RetrievalResult] = {}
    for r in results:
        existing = by_id.get(r.chunk_id)
        if existing is None or r.score > existing.score:
            by_id[r.chunk_id] = r
    return sorted(by_id.values(), key=lambda r: -r.score)


def _plain_fallback(
    query: str,
    embedder: Embedder,
    vector_store: VectorStore,
    top_k: int,
) -> list[RetrievalResult]:
    """Plain vector search — used when the rerank strategy has no base list."""
    emb = embedder.embed_one(query)
    return vector_store.query(emb, top_k=top_k)
