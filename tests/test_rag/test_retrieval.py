"""Tests for hello_agent.rag.retrieval — 4-strategy pipeline + RRF.

Per ENGINEERING.md §7.2.4:
  - ensemble_weights() returns {strategy: weight}, sum = 1.0
  - rrf_fuse() combines ranked lists via reciprocal rank fusion
  - the 4 strategies (rewrite / hyde / multi_query / rerank) all degrade
    gracefully when the LLM is unavailable
  - retrieve() returns a deduplicated, fused top-k list

Tests use a hand-rolled FakeLLMClient (per the project convention) and
a FakeVectorStore so we don't need chromadb to be installed.
"""
from __future__ import annotations

from typing import Any

from hello_agent.core.config import reload_config
from hello_agent.rag.retrieval import (
    ALL_STRATEGIES,
    ensemble_weights,
    multi_query,
    query_rewrite,
    rerank,
    retrieve,
    rrf_fuse,
)
from hello_agent.rag.vector_store import RetrievalResult as VsResult

# ─── Test doubles ------------------------------------------------------------


class FakeLLMClient:
    """Hand-rolled LLM stub — returns a pre-canned JSON list of strings.

    The first message is treated as the user prompt; we sniff the prompt
    for keywords to decide which canned response to return.
    """

    def __init__(self, response: str = "") -> None:
        self.response = response
        self.calls: list[list[Any]] = []

    def chat(self, messages, tools=None, temperature=0.7, max_tokens=None):  # noqa: ARG002
        self.calls.append(messages)
        prompt = messages[0].content if messages else ""

        # Check the most specific markers FIRST. Order matters: rerank's
        # "JSON array of scores" contains "JSON array", so the rewrite
        # branch would otherwise eat it.
        if "JSON array of scores" in prompt:
            text = "[8, 6, 4, 2, 0]"
        elif "relevance ranker" in prompt:
            text = "[8, 6, 4, 2, 0]"
        elif "Write a short passage" in prompt:
            text = "This is a fake hypothetical document body."
        elif "sub-questions" in prompt:
            # multi_query prompt
            text = '["subq 1", "subq 2", "subq 3", "subq 4"]'
        elif "JSON array" in prompt or "JSON list" in prompt:
            # query_rewrite prompt
            text = '["alt 1", "alt 2", "alt 3"]'
        else:
            text = self.response or "[]"

        # Return shape mirrors openai's ChatCompletion.
        class _Msg:
            content = text

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class FakeEmbedder:
    """Returns a fixed-dim zero-ish vector for every input."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        # Return a vector that depends on the *index* of the input, not the
        # text — that way we can deterministically test ordering.
        out: list[list[float]] = []
        for i, _t in enumerate(texts):
            v = [0.0] * self.dim
            v[i % self.dim] = 1.0
            out.append(v)
        return out

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class FakeVectorStore:
    """Pretends to be chromadb. Maps input vectors to canned results.

    The "score" is just 1.0 / (rank + 1) for predictability.
    """

    def __init__(self, results_per_query: list[list[VsResult]] | None = None) -> None:
        # results_per_query[i] is the list returned for the i-th query.
        # If None, generate a default of 3 results.
        if results_per_query is None:
            self.results_per_query = [
                [
                    VsResult(
                        chunk_id=f"q{i}-r{j}",
                        text=f"text for q{i} result {j}",
                        source=f"src-{i}-{j}",
                        score=1.0 / (j + 1),
                        strategy="fake",
                    )
                    for j in range(3)
                ]
                for i in range(8)  # support up to 8 queries
            ]
        else:
            self.results_per_query = results_per_query
        self.call_count = 0
        self.queries: list[list[float]] = []

    def query(self, embedding, *, top_k=8, where=None):  # noqa: ARG002
        self.queries.append(list(embedding))
        idx = min(self.call_count, len(self.results_per_query) - 1)
        self.call_count += 1
        return list(self.results_per_query[idx])[:top_k]


# ─── Tests for ensemble_weights ---------------------------------------------


class TestEnsembleWeights:
    def test_returns_four_strategies(self) -> None:
        weights = ensemble_weights()
        for name in ALL_STRATEGIES:
            assert name in weights

    def test_sum_equals_one(self) -> None:
        weights = ensemble_weights()
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-6, f"sum of weights = {total}"

    def test_default_0_4_0_2_0_2_0_2(self) -> None:
        weights = ensemble_weights()
        # Default config (config.yaml) → exactly the spec'd 0.4/0.2/0.2/0.2.
        assert abs(weights["rewrite"] - 0.4) < 1e-6
        assert abs(weights["hyde"] - 0.2) < 1e-6
        assert abs(weights["multi_query"] - 0.2) < 1e-6
        assert abs(weights["rerank"] - 0.2) < 1e-6


# ─── Tests for rrf_fuse -----------------------------------------------------


class TestRRFFuse:
    def test_rrf_fuse_ranks_docs_in_both_lists_higher(self) -> None:
        a = VsResult(chunk_id="a", text="a", source="s", score=0.9, strategy="x")
        b = VsResult(chunk_id="b", text="b", source="s", score=0.7, strategy="x")
        c = VsResult(chunk_id="c", text="c", source="s", score=0.5, strategy="x")
        list1 = [a, b, c]
        list2 = [b, a, c]
        fused = rrf_fuse([list1, list2])
        assert len(fused) == 3
        # a and b are in both lists → tied at top. c is in only one list
        # (rank 3 in both) → strictly lower.
        c_fused = next(r for r in fused if r.chunk_id == "c")
        for r in fused:
            if r.chunk_id in ("a", "b"):
                assert r.score > c_fused.score

    def test_rrf_fuse_handles_single_list(self) -> None:
        a = VsResult(chunk_id="a", text="a", source="s", score=0.9, strategy="x")
        b = VsResult(chunk_id="b", text="b", source="s", score=0.5, strategy="x")
        fused = rrf_fuse([[a, b]])
        assert [r.chunk_id for r in fused] == ["a", "b"]

    def test_rrf_fuse_handles_empty_input(self) -> None:
        assert rrf_fuse([]) == []

    def test_rrf_fuse_marks_strategy_as_rrf_fused(self) -> None:
        a = VsResult(chunk_id="a", text="a", source="s", score=0.5, strategy="x")
        fused = rrf_fuse([[a]])
        assert fused[0].strategy == "rrf_fused"


# ─── Tests for query_rewrite / multi_query / hyde helpers -------------------


class TestQueryRewrite:
    def test_returns_original_plus_alts(self) -> None:
        llm = FakeLLMClient()
        out = query_rewrite("hello world", llm, n_rewrites=3)
        assert out[0] == "hello world"
        assert len(out) == 4  # original + 3 rewrites

    def test_falls_back_to_original_on_json_error(self) -> None:
        class BadJSON(FakeLLMClient):
            def chat(self, messages, **kw):
                class _M:
                    content = "not valid json {{"

                class _C:
                    message = _M()

                class _R:
                    choices = [_C()]

                return _R()

        out = query_rewrite("q", BadJSON(), n_rewrites=3)
        assert out == ["q"]


class TestMultiQuery:
    def test_returns_original_plus_subqs(self) -> None:
        llm = FakeLLMClient()
        out = multi_query("what is x?", llm, n_queries=4)
        assert out[0] == "what is x?"
        assert len(out) == 5


class TestRerank:
    def test_rerank_blends_cosine_with_llm_score(self) -> None:
        llm = FakeLLMClient()
        candidates = [
            VsResult(
                chunk_id=f"c{i}",
                text=f"text {i}",
                source="s",
                score=0.9 - i * 0.1,
                strategy="x",
            )
            for i in range(5)
        ]
        out = rerank("query", candidates, llm, top_n=5)
        assert len(out) == 5
        # All 5 got re-scored (top_n == 5).
        for r in out:
            assert "llm_rerank_score" in r.metadata

    def test_rerank_top_n_limits_pass(self) -> None:
        llm = FakeLLMClient()
        candidates = [
            VsResult(
                chunk_id=f"c{i}",
                text=f"text {i}",
                source="s",
                score=0.9 - i * 0.05,
                strategy="x",
            )
            for i in range(10)
        ]
        out = rerank("query", candidates, llm, top_n=3)
        # Only the first 3 should have llm_rerank_score metadata.
        scored = [r for r in out if "llm_rerank_score" in r.metadata]
        assert len(scored) == 3
        assert len(out) == 10

    def test_rerank_falls_back_silently_on_json_error(self) -> None:
        class BadJSON(FakeLLMClient):
            def chat(self, messages, **kw):
                class _M:
                    content = "not valid json"

                class _C:
                    message = _M()

                class _R:
                    choices = [_C()]

                return _R()

        candidates = [
            VsResult(
                chunk_id="a",
                text="hi",
                source="s",
                score=0.5,
                strategy="x",
            ),
        ]
        out = rerank("query", candidates, BadJSON(), top_n=5)
        assert out == candidates
        # No metadata was injected because the JSON parse failed.
        assert "llm_rerank_score" not in out[0].metadata


# ─── Tests for retrieve() ---------------------------------------------------


class TestRetrieve:
    def test_retrieve_with_single_strategy(self) -> None:
        """If only `rewrite` is requested, results are the rewrite output."""
        llm = FakeLLMClient()
        embedder = FakeEmbedder()
        store = FakeVectorStore()
        results = retrieve(
            "hello",
            store,  # type: ignore[arg-type]
            embedder,  # type: ignore[arg-type]
            llm,  # type: ignore[arg-type]
            strategies=["rewrite"],
            top_k=5,
        )
        assert len(results) > 0
        assert len(results) <= 5
        # All results should have been produced by the rewrite strategy.
        for r in results:
            assert r.strategy in ("rrf_fused", "fake")

    def test_retrieve_with_all_four_strategies(self) -> None:
        llm = FakeLLMClient()
        embedder = FakeEmbedder()
        store = FakeVectorStore()
        results = retrieve(
            "hello",
            store,  # type: ignore[arg-type]
            embedder,  # type: ignore[arg-type]
            llm,  # type: ignore[arg-type]
            strategies=list(ALL_STRATEGIES),
            top_k=5,
        )
        # Top_k respected.
        assert len(results) <= 5
        # Strategy on the final result is always "rrf_fused" after fusion.
        for r in results:
            assert r.strategy == "rrf_fused"

    def test_retrieve_returns_empty_when_strategies_disabled(self) -> None:
        """If we filter out every strategy, retrieve should still return
        *something* (it falls back to a plain vector search)."""
        reload_config()
        llm = FakeLLMClient()
        embedder = FakeEmbedder()
        store = FakeVectorStore()
        # No matching strategies — we still get a result (the fallback path).
        results = retrieve(
            "hello",
            store,  # type: ignore[arg-type]
            embedder,  # type: ignore[arg-type]
            llm,  # type: ignore[arg-type]
            strategies=[],  # empty list
            top_k=5,
        )
        # Fallback: just one vector search query. Should return results.
        assert len(results) > 0

    def test_retrieve_respects_top_k(self) -> None:
        llm = FakeLLMClient()
        embedder = FakeEmbedder()
        # Each query returns 5 results → fused dedupe should still be capped.
        store = FakeVectorStore(
            results_per_query=[
                [
                    VsResult(
                        chunk_id=f"q{i}-r{j}",
                        text="x",
                        source="s",
                        score=1.0 - j * 0.1,
                        strategy="x",
                    )
                    for j in range(5)
                ]
                for i in range(10)
            ]
        )
        results = retrieve(
            "hello",
            store,  # type: ignore[arg-type]
            embedder,  # type: ignore[arg-type]
            llm,  # type: ignore[arg-type]
            strategies=list(ALL_STRATEGIES),
            top_k=3,
        )
        assert len(results) == 3


# ─── Tests for the LLM-failure path (no API key, broken SDK) ----------------


class TestLLMGracefulDegradation:
    def test_query_rewrite_returns_just_original_on_exception(self) -> None:
        class BrokenLLM:
            def chat(self, *a, **kw):
                raise RuntimeError("no API key")

        out = query_rewrite("q", BrokenLLM(), n_rewrites=3)  # type: ignore[arg-type]
        assert out == ["q"]

    def test_multi_query_returns_just_original_on_exception(self) -> None:
        class BrokenLLM:
            def chat(self, *a, **kw):
                raise RuntimeError("no API key")

        out = multi_query("q", BrokenLLM(), n_queries=4)  # type: ignore[arg-type]
        assert out == ["q"]

    def test_retrieve_still_works_when_llm_raises(self) -> None:
        """Even if all 4 LLM-based strategies fail, retrieve must succeed."""

        class BrokenLLM:
            def chat(self, *a, **kw):
                raise RuntimeError("no API key")

        llm = BrokenLLM()
        embedder = FakeEmbedder()
        store = FakeVectorStore()
        # Should not raise — falls back to plain vector search.
        results = retrieve(
            "q",
            store,  # type: ignore[arg-type]
            embedder,  # type: ignore[arg-type]
            llm,  # type: ignore[arg-type]
            strategies=list(ALL_STRATEGIES),
            top_k=5,
        )
        # We still got 3 results from the FakeVectorStore.
        assert len(results) > 0
