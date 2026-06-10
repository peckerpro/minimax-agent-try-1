# Changelog

All notable changes to `hello-agent-2` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-06-10

The v0.2 release lands the four modules that were skeleton-only in v0.1
(`protocols/`, `skills/`, `web/`, `windows/`) and ships the first polished
public surface (5 runnable examples + tool-authoring guide + project
AGENTS.md + v0.2 release script).

### Added
- Day 6: MCP protocol — `hello_agent/protocols/mcp_client.py`
  (stdio JSON-RPC, list_tools / call_tool, clean shutdown) +
  `mcp_server.py` (exposes all 11 built-in tools as MCP); new
  `hello-agent mcp serve` / `mcp connect` subcommands; registry
  `register_mcp_server()` + circuit-breaker across MCP calls.
- Day 7: Skills system — `hello_agent/skills/loader.py` (parses
  SKILL.md frontmatter + body), `registry.py` (regex + keyword trigger
  matching, per-session activation), 3 builtin skills
  (`file_organize`, `daily_review`, `obsidian_lookup`); ReAct agent
  now injects `<available_skills>` into SYSTEM message;
  `hello-agent skills list|show|install` subcommands.
- Day 8: Web UI — FastAPI backend (`server.py` + 5 route modules:
  chat / sessions / skills / tools / config; SSE streaming with
  `token` / `tool_call` / `tool_result` / `final` events); React 18 +
  Vite 5 + TypeScript frontend (chat panel, sidebar, skills / memory /
  config panels, SSE consumer hook, nanostores state); built assets
  ship under `hello_agent/web/static/`.
- Day 9: Windows integration — `hello_agent/windows/tray.py`
  (pystray icon + menu), `autostart.py` (`HKCU\…\Run` round-trip),
  `env.py` (env probe, consumed by `hello-agent doctor`);
  `hello-agent serve` (uvicorn + tray thread) and
  `hello-agent autostart {enable,disable,status}` entries.
- Day 10: examples + docs — `examples/01_quick_chat.py` through
  `05_mcp_round_trip.py` (each ships `--self-test` for the verifier
  to run offline); `docs/TOOL_AUTHORING.md` (full worked plugin
  example); `docs/ARCHITECTURE.md` (v0.2 minimal ASCII map);
  `AGENTS.md` at the repo root for AI coding agents;
  `scripts/release_check.ps1` (pre-tag validator);
  `tests/test_examples.py` (subprocess-runs every example).
- Asset: `hello_agent/assets/tray.png` (16×16 RGBA).

### Changed
- `hello_agent/__version__` bumped to `0.2.0`.
- `pyproject.toml` version bumped to `0.2.0`.
- README quick-start now mentions `hello-agent serve` for the Web UI
  and adds a v0.2 status table.
- ruff config is unchanged; PLW1514 still enforced.

### Tests
- 5 example self-tests (Day 10), each `--self-test` exits 0
  offline.
- New test modules: `tests/test_protocols/` (Day 6),
  `tests/test_skills/` (Day 7), `tests/test_web/` (Day 8),
  `tests/test_windows/` (Day 9), `tests/test_examples.py` (Day 10).
- Full suite: 433 → 439 passing tests across 12 test packages
  (Day 10 adds 6 example tests; Day 9's 36 windows tests skip on
  non-Windows and re-run on Windows).

### Notes
- No breaking changes vs v0.1 — all v0.1 CLI commands, config keys,
  and public Python API are stable.
- The v0.1 CHANGELOG entry was authored ahead of the v0.2 plan being
  carved out and lists some Day 6-9 features as "Day 5" work; this
  v0.2 entry is the authoritative record of when those features
  actually shipped.

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
