"""hello_agent.rag — Retrieval-Augmented Generation subsystem.

Modules:
  - loader:        file extension dispatch (text/code/office/image -> text)
  - chunker:       sliding-window chunker (512 tokens, 64 overlap)
  - embedder:      OpenAI + local (sentence-transformers) backends
  - vector_store:  chromadb wrapper around CHROMADB_PERSIST_DIR
  - retrieval:     4 strategies (rewrite / hyde / multi_query / rerank) + RRF
  - index_cli:     `hello-agent rag index <path>` / `query <text>` drivers

See ENGINEERING.md §6.7 + §7.2 for the full spec.
"""
from __future__ import annotations

# Public re-exports are deliberately *not* done at import time.
# Importers should reach in for the specific submodule they need; that keeps
# `import hello_agent.rag` cheap and prevents the optional chromadb /
# sentence-transformers deps from being required for CLI work that doesn't
# touch RAG.
