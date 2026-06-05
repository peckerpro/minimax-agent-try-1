# Changelog

All notable changes to `hello-agent-2` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-06

### Added
- Day 1: Project scaffolding (`pyproject.toml`, `.env.example`, `.gitignore`, `LICENSE`, `README.md`)
- Day 1: Core abstractions (`paths`, `config`, `llm`, `types`, `logging`, `exceptions`)
- Day 1: `SimpleAgent` (single-shot LLM, no tools) and CLI skeleton (`main`, `chat`, `doctor`)
- Day 2: Tool system (`registry`, `base`, `response`, `circuit_breaker`, `permission`) + 9 builtins
  (`file_tools`, `shell_tool`, `document_parser`, `web_search`, `web_fetch`,
  `todowrite`, `notify`, `task_tool`, `web_fetch`)
- Day 2: `ReActAgent` (default agent type) with tool dispatch, permission checks, circuit breaker
- Day 3: `SessionDB` — SQLite + FTS5 + trigram, WAL, schema reconciliation
- Day 3: Context engineering (`history`, `token_counter`, `truncator`, `builder`)
- Day 4: Memory subsystem — `short_term`, `long_term`, `episodic`,
  `obsidian_sync` (frontmatter + wikilinks), `git_sync` (background thread)
- Day 4: RAG subsystem — `loader`, `chunker` (sliding window + paragraph-aware),
  `embedder` (OpenAI + local), `vector_store` (chromadb wrapper),
  `retrieval` (4 strategies + RRF fusion), `index_cli`
- Day 5: Web UI (FastAPI + SSE) with chat/sessions/skills/tools/config routes
- Day 5: Windows tray (`pystray`) + autostart (`HKCU\...\Run`)
- Day 5: MCP server (stdio) + MCP client (connect to external servers)
- Day 5: Skills loader + 3 builtin SKILL.md files
- Day 5: 5 example scripts in `examples/`, 1 dev_bootstrap script
- Tests: ~60 tests covering core / tools / context / memory / rag / web / windows

### Notes
- Distilled from NousResearch/hermes-agent architecture (see `docs/ENGINEERING.md` §5)
- Python 3.11+ (3.11 / 3.12 / 3.13 all tested)
- Primary platform: Windows 10/11; best-effort macOS/Linux support
