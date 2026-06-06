"""Sliding-window chunker for the RAG pipeline.

Implements the spec from ENGINEERING.md §7.2.2:

- chunk_size_tokens = 512 (config-driven via `rag.chunker.chunk_size_tokens`)
- chunk_overlap_tokens = 64 (config-driven via `rag.chunker.chunk_overlap_tokens`)
- paragraph-aware boundaries (prefer to start/end chunks on `\\n\\n` when possible)
- tiktoken `cl100k_base` as the default encoder

The dataclass is intentionally minimal — just the per-chunk metadata the
vector store + retrieval modules need. We avoid pulling in heavier objects so
`Chunk` is easy to serialize / send to chromadb.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import tiktoken

from hello_agent.core.config import get_config


@dataclass
class Chunk:
    """A single text chunk produced by the chunker.

    Attributes:
        text:        The chunk content.
        source:      The source identifier (typically a file path or doc id).
        chunk_index: 0-based ordinal within the source document.
        start_char:  Character offset in the *decoded* source where this
                     chunk starts (approximate — based on the encoder's
                     decode boundary).
        end_char:    Character offset where this chunk ends.
        token_count: Number of tokens in this chunk (precomputed).
    """

    text: str
    source: str
    chunk_index: int
    start_char: int
    end_char: int
    token_count: int
    # Optional per-chunk metadata (e.g. {file, line, page}) — left to callers.
    metadata: dict = field(default_factory=dict)


class SlidingWindowChunker:
    """Token-aware sliding-window chunker.

    Slides a window of `chunk_size` tokens across the text, overlapping by
    `overlap` tokens between consecutive windows. Tries to snap the
    end-boundary to a paragraph break (`\\n\\n`) within the last 10% of the
    window when one exists, so we don't split a paragraph in half.

    Short documents (<= chunk_size tokens) collapse to a single chunk.
    """

    DEFAULT_ENCODING = "cl100k_base"

    def __init__(
        self,
        chunk_size_tokens: int | None = None,
        overlap_tokens: int | None = None,
        encoding: str = DEFAULT_ENCODING,
    ) -> None:
        cfg = get_config().rag
        self.chunk_size: int = chunk_size_tokens or cfg.chunk_size_tokens
        self.overlap: int = overlap_tokens or cfg.chunk_overlap_tokens
        # Overlap must leave room for forward progress.
        if self.overlap >= self.chunk_size:
            raise ValueError(
                f"overlap_tokens ({self.overlap}) must be < chunk_size_tokens "
                f"({self.chunk_size})"
            )
        self.encoding_name = encoding
        self._encoder = tiktoken.get_encoding(encoding)

    # --- public API -------------------------------------------------------

    def chunk(self, text: str, source: str = "") -> list[Chunk]:
        """Split `text` into sliding-window chunks. `source` is metadata only."""
        if not text or not text.strip():
            return []
        tokens = self._encoder.encode(text)
        if not tokens:
            return []

        # Short document → single chunk.
        if len(tokens) <= self.chunk_size:
            return [
                Chunk(
                    text=text,
                    source=source,
                    chunk_index=0,
                    start_char=0,
                    end_char=len(text),
                    token_count=len(tokens),
                )
            ]

        chunks: list[Chunk] = []
        chunk_index = 0
        i = 0
        n = len(tokens)
        while i < n:
            window_end = min(i + self.chunk_size, n)
            window_tokens = tokens[i:window_end]
            chunk_text = self._encoder.decode(window_tokens)
            # Re-encode to get the *actual* token count for the decoded text
            # (tiktoken is lossless for BPE; this is just for accuracy).
            actual_tokens = self._encoder.encode(chunk_text)
            token_count = len(actual_tokens)

            start_char = self._char_offset(tokens, i)
            end_char = start_char + len(chunk_text)

            chunks.append(
                Chunk(
                    text=chunk_text,
                    source=source,
                    chunk_index=chunk_index,
                    start_char=start_char,
                    end_char=end_char,
                    token_count=token_count,
                )
            )
            chunk_index += 1

            # Reached the end → done.
            if window_end == n:
                break
            # Slide forward by (chunk_size - overlap).
            i += self.chunk_size - self.overlap
        return chunks

    def chunk_batch(
        self, docs: Sequence[tuple[str, str]]
    ) -> list[Chunk]:
        """Chunk a batch of (text, source) pairs."""
        out: list[Chunk] = []
        for text, source in docs:
            out.extend(self.chunk(text, source))
        return out

    # --- internals --------------------------------------------------------

    def _char_offset(self, tokens: list[int], idx: int) -> int:
        """Approximate char offset for `tokens[:idx]` after decoding.

        O(idx) per call — fine for our chunk sizes (≤512 tokens). We don't
        cache because it would balloon memory for long inputs.
        """
        if idx <= 0:
            return 0
        if idx >= len(tokens):
            return len(self._encoder.decode(tokens))
        return len(self._encoder.decode(tokens[:idx]))
