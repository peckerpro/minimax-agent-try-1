# hello-agent-2

> Personal Windows Python agent — Hermes-inspired with Obsidian-backed memory and advanced RAG.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: v0.2.0](https://img.shields.io/badge/status-v0.2.0-blue)]()

A distillation of [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) architecture,
tailored for a single-user Windows setup. Built around three personal pillars:

1. **Obsidian + Git memory** — every long-term fact becomes a markdown note in your vault, auto-synced to a private GitHub repo.
2. **4-strategy advanced RAG** — `query_rewrite` + `hyde` + `multi_query` + `rerank`, fused via Reciprocal Rank Fusion.
3. **OpenAI-compatible LLM** — works with OpenAI, DeepSeek, Zhipu, Ollama, LM Studio, anything that speaks the chat completions protocol.

## Quick start (Windows / PowerShell)

```powershell
# 1. Install uv (one-time, per machine)
irm https://astral.sh/uv/install.ps1 | iex

# 2. Clone + setup
git clone https://github.com/peckerpro/hello-agent-2.git
cd hello-agent-2
uv venv .venv --python 3.11
.venv\Scripts\Activate.ps1
uv sync --all-extras

# 3. Configure
Copy-Item .env.example .env
# Edit .env: at minimum set LLM_API_KEY

# 4. Verify
uv run hello-agent --version
uv run hello-agent doctor
uv run hello-agent chat "Hello, what's 2+2?"
```

## v0.2 status

| Day | Module | Status |
| --- | --- | --- |
| 1 | Project scaffolding + core abstractions | ✅ |
| 2 | Tool registry + document parser + file/shell tools | ✅ |
| 3 | ReAct loop + SessionDB + context engineering | ✅ |
| 4 | Memory (Obsidian) + RAG (4-strategy retrieval) | ✅ |
| 5 | Web UI skeleton + tray + MCP skeleton | ✅ |
| 6 | MCP protocol adapters (client + server + registry routing) | ✅ |
| 7 | Skills system (SKILL.md loader + registry + 3 builtins) | ✅ |
| 8 | Web UI (FastAPI + React + SSE streaming) | ✅ |
| 9 | Windows integration (tray + autostart + serve + env probe) | ✅ |
| 10 | Examples + docs + CHANGELOG + AGENTS.md + v0.2 tag | ✅ |

Run the v0.2 release check before tagging a new release:

```powershell
.\scripts\release_check.ps1
```

See `docs/ENGINEERING.md` for the full engineering brief and `docs/CHANGELOG.md` for what changed.

## Commands

```powershell
# Chat
uv run hello-agent chat "your question here"
uv run hello-agent chat --session my-session-name

# One-shot
uv run hello-agent run "summarize this PDF"

# Tools
uv run hello-agent tools list
uv run hello-agent tools enable shell_tool
uv run hello-agent tools disable document_parser

# RAG
uv run hello-agent rag index D:\path\to\docs
uv run hello-agent rag query "What is the project structure?"

# Memory
uv run hello-agent memory show
uv run hello-agent memory search "python"
uv run hello-agent memory export "I love VS Code"

# Web UI
uv run hello-agent serve
# → http://127.0.0.1:8648

# MCP
uv run hello-agent mcp serve     # expose tools as MCP server
uv run hello-agent mcp connect ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."]

# Diagnostics
uv run hello-agent doctor
uv run hello-agent doctor --reset-state

# Windows autostart
uv run hello-agent autostart enable
uv run hello-agent autostart disable
```

## Architecture

hello-agent-2 follows a borrowed architecture from `NousResearch/hermes-agent`. See
[`docs/ENGINEERING.md`](docs/ENGINEERING.md) §5 for the full borrowing map.

```
hello_agent/
├── core/        # paths, config, LLM, types, logging, state, exceptions
├── agents/      # simple, react (default), plan_solve, reflection, router
├── tools/       # registry, circuit_breaker, permission + 9 builtins
├── context/     # history, token_counter, truncator, builder
├── memory/      # short_term, long_term, episodic, obsidian_sync, git_sync
├── rag/         # loader, chunker, embedder, vector_store, retrieval
├── protocols/   # mcp_client, mcp_server
├── observability/  # tracer, metrics
├── skills/      # SKILL.md loader + builtin skills
├── windows/     # tray, autostart, env probe
├── web/         # FastAPI server + React static
└── cli/         # typer-based entry point
```

## Why this exists

Most agent frameworks are either too small (toy examples) or too large (multi-tenant
gateway systems). `hello-agent-2` is what one developer actually needs on a single
Windows box: it knows your files, remembers your preferences, can search your
document vault, and doesn't phone home.

## License

MIT © 2026 peckerpro
