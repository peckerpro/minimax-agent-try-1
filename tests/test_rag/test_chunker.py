"""Tests for hello_agent.rag.chunker.SlidingWindowChunker.

Per ENGINEERING.md §7.2.2:
  - chunk_size_tokens = 512 (config default)
  - chunk_overlap_tokens = 64 (config default)
  - paragraph-aware boundaries (soft preference — see tests below)
"""
from __future__ import annotations

import pytest

from hello_agent.rag.chunker import Chunk, SlidingWindowChunker


class TestSlidingWindowChunkerBasic:
    """Smoke + correctness tests for the sliding-window chunker."""

    def test_short_doc_collapses_to_one_chunk(self) -> None:
        chunker = SlidingWindowChunker(chunk_size_tokens=128, overlap_tokens=16)
        chunks = chunker.chunk("hello world", source="s1")
        assert len(chunks) == 1
        c = chunks[0]
        assert c.text == "hello world"
        assert c.source == "s1"
        assert c.chunk_index == 0
        assert c.token_count >= 1
        assert c.start_char == 0
        assert c.end_char == len("hello world")

    def test_empty_text_returns_empty_list(self) -> None:
        chunker = SlidingWindowChunker()
        assert chunker.chunk("", source="s") == []
        assert chunker.chunk("   \n\n  ", source="s") == []

    def test_long_doc_yields_multiple_chunks(self) -> None:
        chunker = SlidingWindowChunker(chunk_size_tokens=128, overlap_tokens=16)
        body = "The quick brown fox jumps over the lazy dog. " * 130  # ~5200 chars
        chunks = chunker.chunk(body, source="s2")
        assert len(chunks) > 1, f"expected multiple chunks, got {len(chunks)}"

    def test_chunk_indices_are_sequential(self) -> None:
        chunker = SlidingWindowChunker(chunk_size_tokens=64, overlap_tokens=8)
        body = ("lorem ipsum dolor sit amet. " * 200)
        chunks = chunker.chunk(body, source="s3")
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_source_propagated_to_all_chunks(self) -> None:
        chunker = SlidingWindowChunker(chunk_size_tokens=64, overlap_tokens=8)
        body = "hello world. " * 200
        chunks = chunker.chunk(body, source="my-source")
        assert all(c.source == "my-source" for c in chunks)
        assert len(chunks) > 0

    def test_chunk_text_is_nonempty(self) -> None:
        chunker = SlidingWindowChunker(chunk_size_tokens=64, overlap_tokens=8)
        body = "abcdef " * 500
        chunks = chunker.chunk(body, source="s4")
        assert all(c.text.strip() for c in chunks)

    def test_default_chunk_size_matches_config(self) -> None:
        """The default chunker should pick up chunk_size=512 from config."""
        from hello_agent.core.config import get_config

        cfg = get_config().rag
        chunker = SlidingWindowChunker()
        assert chunker.chunk_size == cfg.chunk_size_tokens
        assert chunker.overlap == cfg.chunk_overlap_tokens

    def test_explicit_overrides_take_precedence(self) -> None:
        chunker = SlidingWindowChunker(chunk_size_tokens=100, overlap_tokens=10)
        assert chunker.chunk_size == 100
        assert chunker.overlap == 10

    def test_overlap_must_be_less_than_chunk_size(self) -> None:
        with pytest.raises(ValueError, match="overlap_tokens"):
            SlidingWindowChunker(chunk_size_tokens=64, overlap_tokens=64)
        with pytest.raises(ValueError, match="overlap_tokens"):
            SlidingWindowChunker(chunk_size_tokens=64, overlap_tokens=100)


class TestSlidingWindowChunkerOverlap:
    """The overlap region is what gives the retriever continuity."""

    def test_consecutive_chunks_share_tokens(self) -> None:
        chunker = SlidingWindowChunker(chunk_size_tokens=64, overlap_tokens=16)
        body = "alpha bravo charlie delta. " * 200  # > 64 tokens
        chunks = chunker.chunk(body, source="overlap")
        assert len(chunks) >= 2
        # The end of chunk 0 should be past the start of chunk 1.
        assert chunks[1].start_char < chunks[0].end_char
        # But the total length should be close to chunk_size_tokens.
        # We allow some slack because the chunker's end_char is the decoded
        # character position, not a token count.
        assert chunks[0].token_count <= chunker.chunk_size + 5

    def test_last_chunk_ends_at_eof(self) -> None:
        chunker = SlidingWindowChunker(chunk_size_tokens=64, overlap_tokens=8)
        body = "x " * 500  # ~1000 chars
        chunks = chunker.chunk(body, source="eof")
        last = chunks[-1]
        # The end_char of the final chunk should reach the end of the doc.
        assert last.end_char == len(body) or last.end_char >= len(body) - 5


class TestChunkBatch:
    def test_chunk_batch_returns_combined_chunks(self) -> None:
        chunker = SlidingWindowChunker(chunk_size_tokens=64, overlap_tokens=8)
        docs = [
            ("alpha " * 100, "doc1"),
            ("beta " * 100, "doc2"),
        ]
        chunks = chunker.chunk_batch(docs)
        sources = {c.source for c in chunks}
        assert sources == {"doc1", "doc2"}
        assert all(c.token_count > 0 for c in chunks)

    def test_chunk_batch_empty(self) -> None:
        chunker = SlidingWindowChunker()
        assert chunker.chunk_batch([]) == []


class TestChunkDataclass:
    def test_chunk_metadata_default_factory(self) -> None:
        c = Chunk(
            text="hi",
            source="s",
            chunk_index=0,
            start_char=0,
            end_char=2,
            token_count=1,
        )
        assert c.metadata == {}

    def test_chunk_metadata_explicit(self) -> None:
        c = Chunk(
            text="hi",
            source="s",
            chunk_index=0,
            start_char=0,
            end_char=2,
            token_count=1,
            metadata={"file": "x.py", "line": 42},
        )
        assert c.metadata == {"file": "x.py", "line": 42}
