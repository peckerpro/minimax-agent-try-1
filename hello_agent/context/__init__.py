"""Context engineering subsystem.

Submodules:
- history        in-memory list with sliding window
- token_counter  tiktoken-based counter
- truncator      head_tail / middle_out / summarize tool output
- builder        assemble system + history + tools + RAG into final prompt
"""
from __future__ import annotations

# Submodules are lazily imported by their consumers (history, token_counter,
# truncator, builder). We do NOT eagerly import them here, because that would
# force `hello-agent doctor` to pay the cost of tiktoken + tokenizer downloads.
__all__: list[str] = []
