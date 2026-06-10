# AGENTS.md — hello-agent-2 project conventions for AI coding agents

> If you're an AI coding agent (OpenCode, Codex, Cursor, Aider, Devin, Gemini CLI, …)
> working on this repo, **start here**. This file is the entry point for project
> conventions, build commands, and day-by-day context. The full engineering brief
> lives in `docs/ENGINEERING.md` (3916 lines) — read it before making non-trivial
> changes.

## TL;DR for new sessions

| Question | Answer |
| --- | --- |
| Python | 3.11 / 3.12 / 3.13 (any of the three) |
| Package manager | `uv` (mandatory — pip/poetry/conda not supported) |
| Build system | `hatchling` (configured in `pyproject.toml`) |
| Linter | `ruff==0.15.10` with `preview = true` |
| Test runner | `pytest==9.0.2` (asyncio mode auto) |
| Primary OS | Windows 10/11 PowerShell 5.1 |
| LLM client | OpenAI-compatible (`openai==2.24.0`) |
| Current version | **v0.2.0** (tagged on `wt/e5bdcb08`) |

```powershell
# One-shot verify after every change:
uv run ruff check hello_agent/ scripts/ tests/
uv run pytest -q
```

If both pass, your change is mergeable.

## Repo layout

```
hello-agent-2/
├── AGENTS.md                 ← you are here
├── README.md                 ← user-facing quick-start
├── pyproject.toml            ← deps + ruff + pytest config
├── hello_agent/              ← the package (12 sub-packages)
│   ├── core/                 ← leaf-only: paths, config, llm, types, logging, exceptions
│   ├── agents/               ← SimpleAgent / ReActAgent / PlanAndSolve / Reflection / TaskRouter
│   ├── tools/                ← registry + 8 builtin toolsets
│   ├── context/              ← history / token_counter / truncator / builder
│   ├── memory/               ← short_term / long_term / episodic / obsidian_sync / git_sync
│   ├── rag/                  ← loader / chunker / embedder / vector_store / retrieval (4 strategies + RRF)
│   ├── protocols/            ← MCP client + server (Day 6)
│   ├── skills/               ← SKILL.md loader + builtin/ + registry (Day 7)
│   ├── web/                  ← FastAPI server + routes/ + static/ (Day 8)
│   ├── windows/              ← tray / autostart / env probe (Day 9)
│   ├── observability/        ← tracer + metrics
│   └── cli/                  ← typer-based entry points
├── tests/                    ← mirrors hello_agent/ sub-packages + test_examples.py (Day 10)
├── examples/                 ← 5 runnable scripts (01..05), each with --self-test (Day 10)
├── docs/
│   ├── ENGINEERING.md        ← canonical spec (3916 lines)
│   ├── TOOL_AUTHORING.md     ← how to extend tools (Day 10)
│   ├── ARCHITECTURE.md       ← ASCII module map (Day 10)
│   ├── CHANGELOG.md          ← per-release notes
│   └── v0.2-PLAN.md          ← 5-day delivery contract for v0.2
├── scripts/                  ← smoke_*.py (one per module) + release_check.ps1 (Day 10)
└── .harness/                 ← Mavis team plan + agent reins (this repo's CI)
```

## Build commands

```powershell
# First-time setup
uv venv .venv --python 3.11
.venv\Scripts\Activate.ps1
uv sync --all-extras              # installs [all] optional-deps bundle

# Run any hello-agent command without activating the venv
uv run hello-agent --version
uv run hello-agent doctor

# Run a single example
uv run python examples/01_quick_chat.py            # real LLM call
uv run python examples/01_quick_chat.py --self-test # offline smoke
```

## Test commands

```powershell
# Full suite (use this before committing)
uv run pytest -q                                       # ~60-70s, all 439 tests

# Per-day suites (faster feedback)
uv run pytest tests/test_protocols/ -q                 # Day 6 (MCP)
uv run pytest tests/test_skills/ -q                    # Day 7
uv run pytest tests/test_web/ -q                       # Day 8
uv run pytest tests/test_windows/ -q                   # Day 9
uv run pytest tests/test_examples.py -q                # Day 10

# Smoke scripts (one per major module)
uv run python scripts/smoke_agents.py
uv run python scripts/smoke_cli.py
uv run python scripts/smoke_core.py
uv run python scripts/smoke_context.py
uv run python scripts/smoke_rag.py
uv run python scripts/smoke_skills.py
uv run python scripts/smoke_tools.py
```

## Lint commands

```powershell
# Standard check
uv run ruff check hello_agent/ scripts/ tests/

# Auto-fix what's safe
uv run ruff check --fix hello_agent/ scripts/ tests/

# Format (optional — repo doesn't enforce)
uv run ruff format hello_agent/ scripts/ tests/
```

The ruff config enforces:
- `E` / `F` / `I` — pycodestyle, pyflakes, isort
- `PLW1514` — explicit `encoding=` on every file open (Windows cp1252 footgun)
- `B` — bugbear (common pitfalls)
- `UP` — pyupgrade (use modern Python 3.11+ syntax)

Tests relax `PLW1514` so they don't have to thread `encoding=` everywhere.

## Coding conventions

| Topic | Rule |
| --- | --- |
| Imports | Top-level only; lazy-import heavy/optional modules inside functions (annotated with `# noqa: PLC0415`) |
| File I/O | Always pass `encoding="utf-8"` explicitly — `PLW1514` |
| Async | `pytest-asyncio` mode is `auto`; mark coroutine tests with `async def` |
| Logging | `from hello_agent.core.logging import get_logger`; bind `category=` for tool events |
| Errors | Raise `HelloAgentError` subclasses (see `hello_agent.core.exceptions`); never bare `Exception` |
| Tools | Every `@tool` handler returns a `ToolResult`; handlers receive `(args: dict, **kw)` |
| Tests | Use the `tmp_hello_agent_home` fixture to sandbox `$HELLO_AGENT_HOME` |
| Config | Never mutate the shared singleton in tests — use `tmp_hello_agent_home` + `reset_singletons` |

## Layering rules (DO NOT BREAK)

1. **`core/` is leaf-only.** Nothing in `core/` may import from `agents/`, `tools/`,
   `memory/`, `rag/`, `web/`, `windows/`, `skills/`, `protocols/`, or `observability/`.
2. **`protocols/` is independent of `web/`** — the MCP server is pure-Python stdio
   JSON-RPC with no FastAPI/SSE dependency.
3. **`windows/` is OS-gated.** Every module that touches `winreg` / `pystray` /
   `pywin32` lazy-imports those packages and raises a `HelloAgentError` subclass
   on non-Windows platforms. The `tests/test_windows/` suite is marked with
   `@pytest.mark.windows` and skipped on non-Windows.
4. **`web/` owns its static assets** under `hello_agent/web/static/`; the wheel
   build force-includes that directory
   (`pyproject.toml` → `[tool.hatch.build.targets.wheel.force-include]`).
5. **No LangChain / no LlamaIndex.** The project deliberately stays minimal —
   borrow patterns, not dependencies.

## Day-by-day delivery plan

v0.1 (shipped 2026-06-06, tag `v0.1`):

| Day | Module |
| --- | --- |
| 1 | Project scaffolding + `core/` + `SimpleAgent` + CLI skeleton |
| 2 | Tool system (`registry` / `base` / `permission` / `circuit_breaker`) + 9 builtins + `ReActAgent` |
| 3 | `SessionDB` (SQLite + FTS5 + trigram) + context engineering |
| 4 | Memory (Obsidian + Git sync) + RAG (4-strategy + RRF) |
| 5 | Web UI skeleton + tray + MCP skeleton + Skills skeleton |

v0.2 (shipped 2026-06-10, tag `v0.2`, branch `wt/e5bdcb08`):

| Day | Module | Spec |
| --- | --- | --- |
| 6 | MCP protocol adapters | `docs/v0.2-PLAN.md` §Day 6 |
| 7 | Skills system (SKILL.md) | `docs/v0.2-PLAN.md` §Day 7 |
| 8 | Web UI (FastAPI + React + SSE) | `docs/v0.2-PLAN.md` §Day 8 |
| 9 | Windows integration | `docs/v0.2-PLAN.md` §Day 9 |
| 10 | Examples + docs + CHANGELOG + tag | `docs/v0.2-PLAN.md` §Day 10 |

For v0.3 follow-on work, see `.mavis/plans/day10-release-deliverable.md` (5-line
"what's left" note at the bottom).

## How to extend the project

- **Add a new tool?** Read `docs/TOOL_AUTHORING.md` first. Worked example included.
- **Add a new agent?** Subclass `hello_agent.agents.base.Agent` (or copy `SimpleAgent`
  for a single-shot agent). Register in `hello_agent/agents/__init__.py`.
- **Add a new builtin skill?** Drop a `SKILL.md` into `hello_agent/skills/builtin/`.
  Frontmatter + Procedure section are required; triggers are regex + keyword.
- **Add a new web route?** Add a module under `hello_agent/web/routes/` and wire it
  into `hello_agent/web/server.py`. The frontend (`web-ui/src/`) needs a matching
  panel.
- **Add a new CLI subcommand?** Add a `cli/<name>.py`, import it lazily in
  `cli/main.py` with `# noqa: PLC0415`.

## Verification gate before merge

Before opening a PR (or before claiming a task done in a Mavis team plan), run:

```powershell
uv run ruff check hello_agent/ scripts/ tests/
uv run pytest -q
```

Both must exit 0. Then update `docs/CHANGELOG.md` and bump `__version__` in
`hello_agent/__init__.py` + `pyproject.toml`.

For a release, additionally run:

```powershell
.\scripts\release_check.ps1
```

This validates ruff, full pytest, version consistency, and that the tag doesn't
already exist.

## Where to look first

1. **`docs/ENGINEERING.md`** — the canonical spec (3916 lines)
2. **`docs/ARCHITECTURE.md`** — compact ASCII module map
3. **`docs/CHANGELOG.md`** — what changed in each release
4. **`docs/TOOL_AUTHORING.md`** — how to add tools
5. **`.mavis/plans/`** — per-day deliverable reports (what was actually shipped)

## What NOT to do

- Don't add LangChain / LlamaIndex / any heavy agent framework.
- Don't change the `pyproject.toml` dependency pins without an explicit OK — the
  exact-pin policy is intentional (see `docs/ENGINEERING.md` §3).
- Don't add async-everywhere refactors — the agent loop is synchronous for a
  reason (simpler error handling, easier tracing).
- Don't use `git push --force` on `wt/e5bdcb08` — the branch is shared across
  the v0.2 plan.
- Don't commit `.env`, `node_modules/`, `dist/`, `.venv/`, or anything under
  `.harness/test_home/` — see `.gitignore`.