"""Token counting for context budgeting.

Uses tiktoken for OpenAI-family models; falls back to cl100k_base for unknown
models; final fallback is a chars/4 heuristic.
"""
from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

import tiktoken
from tiktoken import Encoding

from hello_agent.core.types import Message

_FALLBACK_ENCODING = "cl100k_base"


@lru_cache(maxsize=8)
def _get_encoding(model: str) -> Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding(_FALLBACK_ENCODING)


def count_text_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Count tokens for a single text string."""
    if not text:
        return 0
    enc = _get_encoding(model)
    return len(enc.encode(text))


def count_tokens(messages: Iterable[Message], model: str = "gpt-4o-mini") -> int:
    """Count tokens for a list of messages.

    Uses a simplified per-message estimate: 4 tokens of overhead (role + metadata)
    plus the content tokens. Good enough for budget tracking; not exact.
    """
    enc = _get_encoding(model)
    total = 0
    for m in messages:
        total += 4  # role + delimiters
        if m.content:
            total += len(enc.encode(m.content))
        if m.tool_calls:
            for tc in m.tool_calls:
                total += len(enc.encode(tc.name))
                total += len(enc.encode(str(tc.arguments)))
    return total
