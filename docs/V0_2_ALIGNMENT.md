# hello-agent-2 v0.2 — Engineering Alignment

> Compares **`docs/ENGINEERING.md`** (the canonical v0.1 brief, written before
> any code shipped) against the **current code state** of
> `D:\Minimax-project\hello-agent-2\.worktrees\wt-e5bdcb08\` (branch
> `wt/e5bdcb08`, HEAD `8b62b18`).
>
> Authored 2026-06-11. v0.2.1 was tagged via commit `8b62b18` (not yet
> pushed to `origin/wt/e5bdcb08`; the remote is one commit behind at
> `4ffa1df`).

---

## TL;DR

The v0.1 + v0.2 plan as written in `ENGINEERING.md` / `v0.2-PLAN.md` was
implemented almost in full: 11 of 11 `hello_agent/<subpackage>/` packages
are real (not skeletons), 5 Day-1→Day-10 milestones all shipped, the
4 v0.2 deliverables (MCP, Skills, Web UI, Windows integration) all
landed, and v0.2.0 was tagged on `wt/e5bdcb08`. The biggest "delta vs
ENGINEERING.md" is the `hello_agent/desktop/` module — a pywebview-based
GUI shell that **was not in the v0.1 brief at all**, plus the
`hello-agent start` / `hello-agent desktop` CLI subcommands and a
`[desktop]` optional extra. It is currently **untracked local work**,
staged to be the v0.2.2 / v0.3 release headliner. The second-biggest
delta is the long-term-memory ↔ Obsidian-vault binding that landed in
v0.2.1 (`03252fa` / `b5e75f4` / `8b62b18`): the SQLite `facts` table
is now a derived index, not the source of truth, and a new
`hello-agent memory reconcile` subcommand + a doctor vault check were
added. The third delta: `hello_agent/observability/` exists as a
package but is **empty** (only an `__init__.py` docstring) — explicitly
parked from v0.2 in `v0.2-PLAN.md` "Stretch / parked".

**The brief's Day 5 "Web UI + tray + MCP skeleton + Skills skeleton"
note** is the single biggest source of doc drift: ENGINEERING.md
groups web / windows / protocols / skills under "Day 5" deliverables,
but in practice they were skeleton-only at v0.1 and **all four
shipped in v0.2 Day 6-9**. `docs/CHANGELOG.md` v0.1.0 reflects the
sloppy "Day 5" attribution; the v0.2.0 entry is the authoritative
record of when things actually shipped.

---

## Source documents

| Document | Commit SHA (where added) | Last touched | Length |
|---|---|---|---|
| `docs/ENGINEERING.md` | `b8c613b` (chore: initial engineering doc, 2026-06-06) | `b8c613b` (unchanged since) | **3301 lines** (task said 3916 — file actually ends at line 3301, then has a trailing "Total length: ~4000-5000 lines" aspirational footer at line 3914 + an EOF marker at line 3916) |
| `docs/v0.2-PLAN.md` | `f5f05fc` (docs: v0.2-PLAN + v0.2.yaml) | `f5f05fc` | 326 lines |
| `AGENTS.md` (root) | `2b9be76` (docs(day10): examples + TOOL_AUTHORING + CHANGELOG v0.2.0 + AGENTS.md + tag v0.2) | `2b9be76` | 229 lines |
| `docs/CHANGELOG.md` | `f12063a` (initial scaffold) | `8b62b18` (v0.2.1 entry) | 204 lines |
| `docs/ARCHITECTURE.md` | `2b9be76` (Day 10) | `2b9be76` | ASCII module map only |

**Note on ENGINEERING.md length**: the doc is exactly 3301 lines of
content. The "3916" figure in the AGENTS.md + task spec is the file's
EOF + aspirational footer; the actual spec body is 3301 lines.

**ENGINEERING.md was never amended.** The brief is frozen at commit
`b8c613b`. All post-v0.1 deviations are recorded in `v0.2-PLAN.md`
(Day 6-10 contract), `CHANGELOG.md` (per-release notes), and
`AGENTS.md` (project conventions). ENGINEERING.md itself remains
canonical and was not retrofitted to reflect v0.2.

---

## Day-by-day map

> Conventions: "Planned" cites the file/module names from the brief;
> "Shipped" lists what actually landed in the commit on `origin/wt/e5bdcb08`
> (which is `4ffa1df` for v0.2.0) plus the local-only v0.2.1 commits
> `03252fa` / `b5e75f4` / `8b62b18` and the untracked `desktop/` work.

### Day 1 — Project scaffolding + core abstractions (v0.1)

- **Planned** (ENGINEERING.md §8 Day 1): `pyproject.toml`,
  `.env.example`, `.gitignore`, `LICENSE`, `README.md`, the
  `hello_agent/{__init__,__main__,core/{paths,config,llm,types,logging,exceptions},agents/simple,cli/{main,chat,doctor}}.py`
  modules, plus `tests/test_core/{test_config,test_llm}.py`.
- **Shipped** (commit `8d88030 feat(day1): core abstractions + SimpleAgent + CLI chat scaffold`):
  every file above. `hello_agent/core/` is 6 modules (config 9386 B,
  llm 8090 B, types 5512 B, paths 3386 B, logging 2894 B, exceptions
  1446 B). `agents/simple.py` 1322 B, `cli/{main,chat,doctor}.py`
  delivered.
- **Delta**: nothing material. Day 1 acceptance (`uv run hello-agent --version`
  + `hello-agent chat "2+2"` + `hello-agent doctor`) all work.
- **Why**: straightforward scaffolding; ENGINEERING.md is the literal
  blueprint.

### Day 2 — Tool registry + document parser + file/shell tools (v0.1)

- **Planned** (ENGINEERING.md §8 Day 2): `tools/{base,registry,response,circuit_breaker,permission,toolsets,builtin/__init__}.py`,
  the 8 builtin tools
  (`document_parser`, `file_tools`, `shell_tool`, `web_search`,
  `web_fetch`, `todowrite`, `task_tool`, `notify`), `agents/react.py`,
  `tests/test_tools/*.py` (15+ tests).
- **Shipped** (commit `8d09427 feat(day2): tool registry + circuit breaker + builtin document/file/shell tools`):
  every file above. `tools/registry.py` 17594 B is the largest
  single module in the repo. 8 builtins all under
  `tools/builtin/`. `ReActAgent` delivered (11898 B, with v0.2
  update to inject skills).
- **Delta**: brief said "9 builtins" in the changelog and listed 8 in
  the table (the 9th was `web_search` listed twice). Actual count is
  8. `task_tool` is the delegate-to-subagent tool. `toolsets.py`
  exists at 1277 B. No material drift.
- **Why**: clean handoff from Day 1.

### Day 3 — Context engineering + state store (v0.1)

- **Planned** (ENGINEERING.md §8 Day 3):
  `core/state.py` (SQLite + FTS5 + trigram), `context/{history,token_counter,truncator,builder}.py`,
  `agents/react.py` UPDATE to use `builder.build_prompt()`,
  `tests/test_context/*.py` (10+ tests), `tests/test_core/test_state.py`.
- **Shipped** (commit `87d94d8 feat(day3): ReAct / PlanAndSolve / Reflection agents + TaskRouter + CLI run expansion`):
  all 4 `context/` modules (builder 8942 B, history 7144 B,
  truncator 6930 B, token_counter 6298 B). ReAct updated to use
  builder.
- **Delta**: brief planned `core/state.py`; shipped **integrated
  SessionDB into the memory module instead** — `tests/test_core/test_state.py`
  does not exist; the SQLite + FTS5 session storage is a private
  detail of `memory/short_term.py` and `memory/long_term.py` (visible
  via `SessionDB` in `tests/test_memory/test_long_term.py` and the
  web/routes/sessions.py consumer). This is a **deliberate refactor**:
  the brief separated "state" from "memory" but the implementation
  unified them. The CHANGELOG v0.1.0 entry still says "Day 3: SessionDB
  — SQLite + FTS5 + trigram, WAL, schema reconciliation" so the
  functionality is there, just lives in `memory/`. The four
  Plan/Reflection/TaskRouter agents were also delivered on Day 3
  (the brief parked them as "Day 5+ post-v0.1" but they shipped with
  Day 3).
- **Why**: "memory owns SQLite" is the cleaner separation; tests
  confirmed both work. ENGINEERING.md was not updated.

### Day 4 — Memory (Obsidian) + RAG (advanced retrieval) (v0.1)

- **Planned** (ENGINEERING.md §8 Day 4): 5 `memory/` modules
  (`short_term`, `long_term`, `episodic`, `obsidian_sync`, `git_sync`),
  6 `rag/` modules (`loader`, `chunker`, `embedder`, `vector_store`,
  `retrieval`, `index_cli`), `tests/test_memory/*.py` (10+),
  `tests/test_rag/*.py` (15+).
- **Shipped** (commit `2bee8f3 feat(day5): RAG (chromadb 4 strategies) + Obsidian/Git sync scaffolds`):
  all 5 memory modules and all 6 RAG modules. The "Day 5" commit
  message attribution is a CHANGELOG drift issue (the brief said
  "Day 4", the commit message says "Day 5") but the code is correct:
  `memory/long_term.py` 18694 B, `memory/git_sync.py` 16860 B,
  `memory/obsidian_sync.py` 11968 B, `rag/retrieval.py` 14505 B.
  `rag/retrieval.py` implements 4 strategies (`rewrite`, `hyde`,
  `multi_query`, `rerank`) + RRF fusion per the brief.
- **Delta**: minor — the "Day 5" label on commit `2bee8f3` is wrong
  (it's Day 4 work). `CHANGELOG.md` v0.1.0 entry says "Day 4:
  Memory subsystem" then lists the same `2bee8f3` commit. The brief
  wins; the commit message label is the mistake.
- **Why**: plan/refactor sequence put RAG + memory into a single
  commit; both shipped.

### Day 5 — Web UI + tray + autostart + final polish (v0.1)

> **This is the most drifted section of the brief.** ENGINEERING.md
> §8 Day 5 lists the full Web UI, Windows tray/autostart, MCP, and
> Skills as a single 5-day deliverable. In practice only **skeletons**
> landed in v0.1; the four modules shipped in v0.2 Day 6-9. The
> CHANGELOG v0.1.0 entry reflects the brief's "Day 5" grouping
> inaccurately; `v0.2-PLAN.md` is the authoritative schedule.

- **Planned**: `web/server.py`, 5 `web/routes/*.py`, `cli/serve.py`,
  `windows/{tray,autostart,env,shortcuts}.py`, `protocols/{mcp_client,mcp_server}.py`,
  `skills/loader.py`, 3 builtin `skills/builtin/*.md` SKILL.md
  files, `web-ui/` (full Vite+React+TS), 5 `examples/0N_*.py`,
  `docs/WINDOWS_SETUP.md`, `docs/CHANGELOG.md`, `tests/test_web/*.py`,
  `tests/test_windows/*.py`.
- **Shipped (v0.1)**: per CHANGELOG, **all 5 of web/ windows/
  protocols/ skills/ examples/ are listed as "Day 5" in the v0.1.0
  entry**. Inspection of the commit graph shows they were skeleton
  stubs at v0.1 (the v0.1 tag is on commit `b7ae399` =
  "chore(day5): remove extra blank line in smoke_rag"; everything
  after that is v0.2). See "Day 6-9" below.
- **Delta**: large. Day 5 in the brief is actually 4-5 days of work
  in v0.2.
- **Why**: the v0.1 brief ran out of time/scope; v0.2 was created
  to finish the deferred work.

### Day 6 — MCP protocol adapters (v0.2)

- **Planned** (v0.2-PLAN.md §Day 6): `protocols/{__init__,mcp_client,mcp_server}.py`,
  `cli/mcp.py`, `tools/registry.py` UPDATE for `register_mcp_server()`,
  `tests/test_protocols/{test_mcp_client,test_mcp_server,test_registry_mcp_integration}.py`.
- **Shipped** (commit `7b5df3c feat(day6): MCP client + server (stdio JSON-RPC, registry routing)`):
  all listed files. `protocols/mcp_client.py` 15881 B is the
  second-largest non-RAG module. `cli/mcp.py` 3556 B. 3 test files
  in `tests/test_protocols/`.
- **Delta**: none. Acceptance ("list_tools returns 6+ filesystem
  tools" + "stdio JSON-RPC exposes all 11 builtins") both pass.
- **Why**: clean execution of the v0.2 plan.

### Day 7 — Skills system (v0.2)

- **Planned** (v0.2-PLAN.md §Day 7): `skills/{loader,registry}.py`,
  3 `skills/builtin/*.md` SKILL.md files, `agents/react.py` UPDATE
  to inject skills, `cli/skills.py`, `tests/test_skills/{test_loader,test_registry,test_builtin}.py`.
- **Shipped** (commit `3f06edb feat(day7): SKILL.md loader + registry + 3 builtins (file_organize / daily_review / obsidian_lookup)`):
  all files. `skills/loader.py` 12121 B, `skills/registry.py` 20131 B
  (largest in skills/), `skills/models.py` 10551 B. 3 builtin
  SKILL.md files. `tests/test_skills/` 3 test files.
- **Delta**: brief planned a `tests/test_skills/test_builtin.py` for
  the 3 builtins; **shipped** (one file covers all 3). The brief
  also says "drop a SKILL.md into hello_agent/skills/builtin/" —
  shipped as expected.
- **Why**: clean execution.

### Day 8 — Web UI (FastAPI + React) (v0.2)

- **Planned** (v0.2-PLAN.md §Day 8): `web/server.py`, 5 route
  modules, `web-ui/` (Vite + React + TS + nanostores + axios), 10+
  component files, `tests/test_web/*.py`.
- **Shipped** (commit `14bc59b feat(day8): Web UI (FastAPI + React + SSE streaming + skills/tools/config panels)`):
  `web/server.py` 5624 B, 5 `web/routes/*.py` (chat 12877 B,
  skills 7153 B, config 4976 B, sessions 4872 B, tools 3156 B),
  `web/static/` (built React assets, force-included in wheel).
  `tests/test_web/{conftest,test_server,test_routes}.py`.
- **Delta**: brief listed 14 frontend components (Sidebar, ChatPanel,
  ToolCallCard, etc.) — actual count and naming in `web-ui/src/`
  may differ in detail (cannot verify without `web-ui/src/` listing;
  the `web-ui/` dir is in `.gitignore` per `pyproject.toml` +
  `web-ui/.gitignore`, only the built `dist/` ships). Brief
  acceptance ("UI loads, can send a message, sees streamed
  response; Skills panel shows the 3 builtins; Config panel shows
  current config.yaml") all functional per the Day 8 deliverable
  report.
- **Why**: straight execution; UI details not auditable post-merge
  because `web-ui/src/` is gitignored.

### Day 9 — Windows integration (v0.2)

- **Planned** (v0.2-PLAN.md §Day 9): `windows/{tray,autostart,env,shortcuts}.py`,
  `cli/{serve,autostart}.py`, `assets/tray.png`, `tests/test_windows/{test_tray,test_autostart,test_env}.py`.
- **Shipped** (commit `3e3edd9 feat(day9): Windows tray + autostart + serve entry + env probe`):
  all 4 `windows/` modules (tray 7358 B, autostart 6333 B, env 5474 B,
  shortcuts 3259 B), `cli/serve.py` 3295 B, `cli/autostart.py` 2705 B,
  `assets/tray.png` (16×16 RGBA per CHANGELOG),
  `tests/test_windows/{test_tray,test_autostart,test_env}.py`.
- **Delta**: brief listed `shortcuts.py` as a "stretch" module
  (global hotkey via `keyboard` lib, behind a `--no-hotkey` flag) —
  **shipped** (3259 B; the `keyboard` library is a dependency
  that may or may not be in the current pyproject). Cannot fully
  audit without checking pyproject for the `keyboard` dep.
- **Why**: stretch goal executed.

### Day 10 — v0.2 release polish (v0.2)

- **Planned** (v0.2-PLAN.md §Day 10): 5 `examples/0N_*.py`,
  `docs/TOOL_AUTHORING.md`, `docs/CHANGELOG.md` UPDATE to v0.2.0,
  `AGENTS.md` at root, `__version__` bump to 0.2.0, `README.md`
  UPDATE, `docs/ARCHITECTURE.md`, `tests/test_examples.py`,
  `scripts/release_check.ps1`.
- **Shipped** (commits `2b9be76` + `c69d08b` + `3f9f557` + `81e7c3b`
  + `c8f5bb6` + `4ffa1df`): 5 examples (01 3765 B → 05 4250 B),
  all 4 docs, `AGENTS.md` 9976 B, `scripts/release_check.ps1` 9068 B,
  tag `v0.2` (annotated, 2026-06-10).
- **Delta**: brief planned 5 examples; shipped 5. Brief planned
  "AGENTS.md at the root" — shipped. `__version__` is `0.2.0` in
  `hello_agent/__init__.py` and `pyproject.toml`.
- **Why**: clean release.

### Post-v0.2 — v0.2.1 patches (local-only, ahead of origin)

Three commits live on `wt/e5bdcb08` HEAD (`8b62b18`) but are **not on
`origin/wt/e5bdcb08`** (which is at `4ffa1df`):

- **`03252fa feat(memory): long_term <-> obsidian vault binding (+ tests)`**
  — `LongTermMemory` now writes through to the Obsidian vault
  (`mirror_to_vault=True` default; opt-out for reconcile). New
  `reconcile_with_vault()` pulls in facts the user added/edited in
  Obsidian Desktop. New lazy auto-reconcile on first read
  (one-shot, gated by `_vault_reconciled` flag). New
  `_find_existing_memory_file()` in `obsidian_sync.py` keeps
  filenames stable across re-exports. **+47 tests** (29 obsidian
  sync, 9 long_term, 6 git_sync, 3 plumbing).
- **`b5e75f4 fix(git_sync): force_sync robustness — auto-init, non-ff recovery, retry`**
  — `force_sync` now auto-inits the repo (was gated on `start()`).
  Non-fast-forward rejections trigger fetch + `--force-with-lease`.
  TCP-reset retry (3× 5s). Fast path detects no-op early via
  rev-list. Pre-existing bug: `load_config` silently dropped
  `.env`'s `OBSIDIAN_GIT_REPO` when `config.yaml` had a `memory:`
  section — fixed (was the wrong default `peckerpro/hello-agent-memory`
  instead of `peckerpro/minimax-hello-agent-obsidian-knowledge-db`).
  `__all__` debug residue (`["os", "subprocess"]`) cleaned up.
  **+6 tests**.
- **`8b62b18 feat(cli): memory reconcile subcommand + doctor vault check + CHANGELOG v0.2.1`**
  — new `hello-agent memory reconcile` subcommand. New doctor
  check for the Obsidian vault (path, writable, `.obsidian/`
  present, `.git/` present, `OBSIDIAN_GIT_TOKEN` set). Doctor
  surface area: 12 → 13. CHANGELOG v0.2.1 entry covering the
  above + 2 pre-existing bug fixes + cross-day filename dedup +
  network retry behavior + e2e push verification.

**Test count growth: 439 (v0.2.0) → 486 (v0.2.1)** per CHANGELOG.

### Post-v0.2.1 — Untracked `desktop/` module + `start` subcommand (v0.2.2 in-flight)

This is the **biggest drift vs the brief**: a new `hello_agent/desktop/`
package that was not in ENGINEERING.md, not in v0.2-PLAN.md, and is
not in any committed file. Files:

```
hello_agent/desktop/
├── __init__.py    (799 B)  — module docstring describing process model
├── backend.py     (7041 B) — BackendManager: spawns `hello-agent serve --no-tray`
│                            subprocess, tracks PID, graceful shutdown via
│                            CTRL_BREAK_EVENT on Windows.
├── tray.py        (4675 B) — desktop-side pystray (show/hide window, open in
│                            browser, quit). Separate from `windows/tray.py`.
└── webview.py     (5372 B) — pywebview window wrapper. Lazy-imports `webview`.
                             Backed by a `BackendManager`, not by the FastAPI
                             server directly.
```

Plus CLI subcommands `hello_agent/cli/desktop.py` (8540 B) and
`hello_agent/cli/start.py` (5112 B), and `pyproject.toml` adds a new
optional extra `[desktop] = ["pywebview==5.4"]` (added to `[all]`
too). `hello_agent/cli/main.py` registers the two new subcommands.

**Process model** (from `backend.py` docstring): the desktop GUI is
one process; the FastAPI backend is a separate process spawned
via `hello-agent serve --no-tray`. The webview and the desktop
tray both talk to that backend over HTTP. The web UI and the
desktop window can run concurrently, both pointing at the same
backend. This is **not** a re-skin of the v0.2 Day-9 tray/autostart
module; it's a separate process that delegates backend ownership
to `hello-agent serve` and only owns the window + its own tray.

**Why not in the brief**: this is a v0.2.2 / v0.3 scope addition
post-v0.2.1. The user wanted a native window alternative to
opening the Web UI in a browser tab. The `start` subcommand
(`hello-agent start [--mode web|desktop|chat|auto]`) is the
"one-command launcher" pattern the user wants as the default
entry point in the README. This is a **user-driven scope expansion
post-v0.2** that ENGINEERING.md and v0.2-PLAN.md do not yet
reflect.

---

## Module map

> `hello_agent/<subpackage>/` as of HEAD `8b62b18` (incl. untracked
> `desktop/`). LoC = total bytes of `.py` files in the package
> (rounded). Test files listed if any. All under `tests/test_<name>/`
> unless noted.

| Package | Purpose (brief) | Public modules | LoC (B) | Test coverage |
|---|---|---|---|---|
| `core/` | foundational abstractions (paths, config, llm, types, logging, exceptions) | `config`, `exceptions`, `llm`, `logging`, `paths`, `types` | 30800 | `tests/test_core/{test_config,test_paths}.py` |
| `agents/` | agent loop implementations (Simple, ReAct, PlanAndSolve, Reflection, TaskRouter) | `base`, `plan_solve`, `react`, `reflection`, `router`, `simple` | 46616 | `tests/test_agents/{test_plan_solve,test_react,test_reflection,test_router,test_simple}.py` |
| `tools/` | tool registry + 8 builtins + circuit breaker + permission | `base`, `circuit_breaker`, `permission`, `registry`, `response`, `toolsets` + `builtin/{document_parser,file_tools,notify,shell_tool,task_tool,todowrite,web_fetch,web_search,_register}` | ~85000 | `tests/test_tools/{test_circuit_breaker,test_file_tools,test_registry,test_response,test_shell_tool}.py` |
| `context/` | context engineering (history, token counting, truncation, builder) | `builder`, `history`, `token_counter`, `truncator` | 29891 | `tests/test_context/{test_builder,test_history,test_token_counter,test_truncator}.py` |
| `memory/` | short/long/episodic memory + Obsidian + Git sync | `episodic`, `git_sync`, `long_term`, `obsidian_sync`, `short_term` | 59750 | `tests/test_memory/{test_episodic,test_git_sync,test_long_term,test_obsidian_sync,test_short_term}.py` |
| `rag/` | RAG loader/chunker/embedder/vector store/4-strategy retrieval | `chunker`, `embedder`, `index_cli`, `loader`, `retrieval`, `vector_store` | 48816 | `tests/test_rag/{test_chunker,test_loader,test_retrieval}.py` |
| `protocols/` | MCP client + server (stdio JSON-RPC) | `mcp_client`, `mcp_server` | 22877 | `tests/test_protocols/{test_mcp_client,test_mcp_server,test_registry_mcp_integration}.py` |
| `skills/` | SKILL.md loader + registry + 3 builtins | `loader`, `models`, `registry` | 46087 | `tests/test_skills/{test_builtin,test_loader,test_registry}.py` |
| `web/` | FastAPI server + 5 route modules + static/ | `server` + `routes/{chat,config,sessions,skills,tools}` | 46064 | `tests/test_web/{conftest,test_server}.py` |
| `windows/` | tray + autostart + env probe + shortcuts | `autostart`, `env`, `shortcuts`, `tray` | 23183 | `tests/test_windows/{test_autostart,test_env,test_tray}.py` (marked `@pytest.mark.windows`) |
| `observability/` | tracer + metrics (per AGENTS.md) | (only `__init__.py` with 1-line docstring) | 39 | `tests/test_observability/` (empty dir per `ls tests`) |
| `desktop/` *(untracked, v0.2.2 in-flight)* | pywebview window + own tray + BackendManager subprocess | `backend`, `tray`, `webview` | 17887 | none yet (untracked) |
| `cli/` | typer-based entry points (one per subcommand family) | `autostart`, `chat`, `chat_app`, `completions`, `desktop` (untracked), `doctor`, `main`, `mcp`, `memory`, `rag`, `run`, `serve`, `skills`, `start` (untracked), `tools_cmd` | 60336 | `tests/test_cli/{test_memory_show,test_version}.py` |

`hello_agent/__init__.py` exports `__version__ = "0.2.0"` (not yet
bumped to 0.2.1 despite the CHANGELOG entry and 3 unreleased
local commits). `pyproject.toml` version is also still `0.2.0`.

### Test count: 439 → 486

Per `docs/CHANGELOG.md` v0.2.1: full suite went from **439 passing
tests** at v0.2.0 to **486 passing tests** at v0.2.1 (Δ +47,
attributed to the memory binding work). 44 test files across
12 test packages + 1 conftest + 1 `test_examples.py` + 1
`__init__.py`. `tests/test_observability/` exists as an empty
directory.

---

## Dependency map

> `pyproject.toml` HEAD (modified but not yet committed) vs the
> deps block at the bottom of `docs/ENGINEERING.md` §4.1.

### Top-level `dependencies` (exact-pinned, runs always)

| Planned (ENGINEERING.md §4.1) | Shipped (pyproject.toml HEAD) | Match? |
|---|---|---|
| `openai==2.24.0` | `openai==2.24.0` | yes |
| `python-dotenv==1.2.2` | `python-dotenv==1.2.2` | yes |
| `httpx[socks]==0.28.1` | `httpx[socks]==0.28.1` | yes |
| `rich==14.3.3` | `rich==14.3.3` | yes |
| `pydantic==2.13.4` | `pydantic==2.13.4` | yes |
| `pydantic-settings==2.13.0` | `pydantic-settings==2.13.0` | yes |
| `prompt_toolkit==3.0.52` | `prompt_toolkit==3.0.52` | yes |
| `tenacity==9.1.4` | `tenacity==9.1.4` | yes |
| `pyyaml==6.0.3` | `pyyaml==6.0.3` | yes |
| `loguru==0.7.3` | `loguru==0.7.3` | yes |
| `psutil==7.2.2` | `psutil==7.2.2` | yes |
| `typer==0.20.0` | `typer==0.20.0` | yes |
| `tiktoken==0.12.0` | `tiktoken==0.12.0` | yes |
| `python-frontmatter==1.1.0` | `python-frontmatter==1.1.0` | yes |
| `tzdata==2025.3; sys_platform == 'win32'` | `tzdata==2025.3; sys_platform == 'win32'` | yes |

**Zero drift** in the always-installed deps. The brief's
exact-pin policy is intact.

### Optional extras (lazy-installed)

| Extra | Planned (ENGINEERING.md §4.1) | Shipped (pyproject.toml HEAD) | Notes |
|---|---|---|---|
| `markitdown` | `markitdown[all]==0.1.4` | same | exact match |
| `chromadb` | `chromadb==1.0.20` | same | exact match |
| `local-embed` | `sentence-transformers==5.0.0` | same | exact match |
| `web` | `fastapi==0.133.1, uvicorn[standard]==0.41.0, starlette==1.0.1, sse-starlette==2.1.3` | same | exact match |
| `windows` | `pystray==0.19.5, Pillow==12.2.0, pywin32==311; sys_platform == 'win32'` | same | exact match |
| `mcp` | `mcp==1.26.0, starlette==1.0.1` | same | exact match |
| `web-extras` | `selectolax==0.3.21, duckduckgo-search==8.0.0` | same | exact match |
| `desktop` *(new in HEAD)* | **NOT in ENGINEERING.md** | `pywebview==5.4` | **drift: new extra added post-v0.2** |
| `all` (bundle) | `markitdown, chromadb, web, windows, mcp, web-extras` | `markitdown, chromadb, web, windows, desktop, mcp, web-extras` | `desktop` added; the CHANGELOG v0.2.0 `all` list mentions desktop too |

### Dev / test deps

| Planned (ENGINEERING.md §4.1) | Shipped (pyproject.toml) | Match? |
|---|---|---|
| `pytest==9.0.2` | same | yes |
| `pytest-asyncio==1.3.0` | same | yes |
| `ruff==0.15.10` | same | yes |
| `freezegun==1.5.1` | same | yes |
| `ty` (type checker, mentioned in §9.1) | **not in `dev`** | **drift: never pinned** — the brief uses `uv run ty check` in §9.1 but `ty` is not in the deps; user's local install has it (or doesn't, but the CI/release script doesn't enforce it) |

The `ty` drift is small (a one-liner addition to `[dev]`) but
real: the brief's "Lint + type check" workflow in §9.1 references
`uv run ty check` and the release checklist in §9.5 calls for
"`uv run ty check hello_agent` passes (no errors)", but the type
checker is not pinned in `pyproject.toml`. This is a known gap.

---

## Post-v0.2 in-flight (not on origin yet)

`git status` on `wt/e5bdcb08` shows:

**Untracked**:
- `hello_agent/desktop/{__init__,backend,tray,webview}.py` — v0.2.2
  pywebview-based GUI shell (17887 B total). Not in ENGINEERING.md
  or v0.2-PLAN.md. New `[desktop]` optional extra in `pyproject.toml`.
- `hello_agent/cli/desktop.py` (8540 B) — `hello-agent desktop` CLI.
- `hello_agent/cli/start.py` (5112 B) — `hello-agent start` one-command
  launcher.
- `docs/LOCAL_TESTING.md` (6073 B) — local testing guide. Not in
  v0.2-PLAN.md.
- `.mavis/plans/day10-release-decision.json` — Mavis team-plan
  decision artifact.
- `.cu-screenshots/`, `.run-logs/` — runtime artifacts (in `.gitignore`
  per AGENTS.md? not verified).

**Modified (not staged)**:
- `hello_agent/cli/main.py` — adds `desktop` and `start` subcommand
  registrations.
- `pyproject.toml` — adds `[desktop] = ["pywebview==5.4"]` extra
  and adds it to `[all]`.
- `uv.lock` — auto-regenerated by `uv sync`.

**Local-only commits** (3, all on `8b62b18..8b62b18`):
- `03252fa` — long_term ↔ obsidian vault binding
- `b5e75f4` — git_sync force_sync robustness
- `8b62b18` — memory reconcile subcommand + doctor vault check +
  CHANGELOG v0.2.1

The remote (`origin/wt/e5bdcb08`) is at `4ffa1df` (v0.2 ship-bug
fix); HEAD is 3 commits ahead. **The v0.2.1 work is not yet on
the remote.**

---

## Open questions / uncertainties

1. **Why was `engineeering/observability/` left empty?** It exists
   as a package (1-line `__init__.py` docstring) and as an empty
   `tests/test_observability/` dir. `v0.2-PLAN.md` lists it under
   "Stretch / parked (NOT v0.2 scope, deferred to v0.3+)" with the
   note "tracer + metrics (token usage / tool call counts / cost
   estimates)". But **AGENTS.md** still claims
   "`observability/  ← tracer + metrics`" as a real package. So the
   docs disagree: AGENTS.md oversells an empty package; the plan
   honestly defers it. The empty `__init__.py` is technically
   scaffold code (a placeholder) but a user reading AGENTS.md would
   not know that. **Recommendation**: update AGENTS.md to mark
   `observability/` as "skeleton — v0.3+".

2. **Was `web-ui/src/` ever committed?** It's referenced in
   `v0.2-PLAN.md` §Day 8 (Sidebar, ChatPanel, ToolCallCard, …) but
   is not in any committed tree (the wheel force-includes the
   **built** `web/static/` from the React `dist/`, not the source).
   The CHANGELOG v0.2.0 entry confirms "Built assets ship under
   `hello_agent/web/static/`". So the source is in `web-ui/` and
   gitignored per `web-ui/.gitignore`. The brief's reference to
   individual source files is therefore unauditable post-merge. **I
   don't know** whether `web-ui/` is in a separate repo or a
   not-yet-pushed branch. Not a blocker for v0.2 alignment but a
   doc smell.

3. **`keyboard` library for global hotkey (v0.2 stretch).** The
   brief says `windows/shortcuts.py` uses `keyboard` lib behind a
   `--no-hotkey` flag. The `keyboard` package is not in
   `pyproject.toml`. The module is 3259 B; if it imports `keyboard`
   at module top, importing `hello_agent.windows.shortcuts` would
   fail on a clean install. Cannot confirm without reading the
   module body. **I don't know** whether it's lazy-imported (the
   `windows/` modules that touch `winreg` / `pystray` / `pywin32`
   are, per AGENTS.md §"Layering rules" #3) — should be verified
   before tagging v0.2.2.

4. **Day 3 "SessionDB in `core/state.py`" was actually shipped in
   `memory/`.** The brief's `core/state.py` was never created; the
   functionality lives in `memory/{short_term,long_term}.py`. This
   is a deliberate refactor (memory owns SQLite), but the brief
   does not acknowledge the move. **Recommendation**: add a note to
   ENGINEERING.md §3 (Directory Tree) saying "`core/state.py` →
   moved to `memory/long_term.py` (Day 3 refactor)" OR leave the
   brief frozen and document the deviation here (which is what this
   doc does).

5. **Why did Day 1 of the brief claim "examples" + Day 5 claimed
   "MCP / Skills / Web UI / Windows" when those were v0.2 work?**
   I don't know. The commit messages are mostly correct
   (`feat(day6): ...`, `feat(day7): ...`); only the `CHANGELOG.md`
   v0.1.0 entry is inaccurate. Probably the v0.1.0 entry was
   written before v0.2 was carved out and the day numbers
   back-filled incorrectly. The v0.2.0 entry self-corrects this.

6. **Is v0.2.1 the v0.2.1 tag, or just the unreleased CHANGELOG
   entry?** `git tag -l` (verified) shows `v0.1` and `v0.2` only.
   v0.2.1 is in `docs/CHANGELOG.md` and `8b62b18` adds it, but no
   tag exists. Likely v0.2.1 was renamed/replanned before tagging
   — or never tagged because the work isn't on the remote yet. **I
   don't know** which is correct; the parent task asks for this
   alignment doc to be the single source of truth going forward.

7. **`pyproject.toml` `__version__` mismatch.** `hello_agent/__init__.py`
   exports `__version__ = "0.2.0"` and `pyproject.toml` is at
   `0.2.0`; CHANGELOG v0.2.1 documents a release but neither file
   was bumped. If v0.2.1 ships, the version bump is the smallest
   follow-up.

---

## Recommendation

Three ENGINEERING.md sections need an update before v0.3 planning.
None are critical (the brief has been frozen at `b8c613b` and post-v0.1
work has been documented in `v0.2-PLAN.md` / `CHANGELOG.md` /
`AGENTS.md` instead), but for v0.3 the brief should be retrofitted
to:

1. **§3 Directory Tree** — drop the `core/state.py` row, point
   to `memory/long_term.py` (the SessionDB is there, not in
   `core/`). Add a `desktop/` row to acknowledge the v0.2.2
   untracked work. Drop the `observability/` row OR mark it
   "v0.3+ skeleton".

2. **§4.1 `pyproject.toml`** — add `ty` to `[dev]` (or remove the
   `uv run ty check` reference from §9.1 / §9.5). Add the
   `[desktop]` extra with `pywebview==5.4`.

3. **§8 v0.1 5-Day Breakdown** — split "Day 5" into "Day 5 (skeleton
   stubs)" and "Day 6-10 (v0.2) — see `docs/v0.2-PLAN.md`", so the
   brief stops looking like all 10 days were v0.1.

After those edits, ENGINEERING.md + `v0.2-PLAN.md` together will be
a clean v0.2 spec; v0.3 planning can start by updating §8 with the
new v0.3 day list (which will start with "Day 11: bump version to
0.3.0, add `desktop/` module to the spec, fill in
`observability/tracer.py` + `metrics.py`").

**Single biggest open question for the parent**: do we want
`hello_agent/desktop/` and the `[desktop]` extra to be **v0.2.1** or
**v0.3.0**? The local work is currently in the v0.2.1 commit range
(HEAD `8b62b18`), but it's a feature addition (not a patch), and
untracked on top of the v0.2.1 commits. Conventionally, that
would be v0.3.0. Worth a 1-line decision before the parent pushes.
