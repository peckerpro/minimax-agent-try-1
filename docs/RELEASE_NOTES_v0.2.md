# hello-agent-2 v0.2.0 — Release Notes

**Release date:**2026-06-10
**Tag:** `v0.2` (lightweight tag at commit `2b9be76`)
**Branch:** `wt/e5bdcb08` (worktree `D:\Minimax-project\hello-agent-2\.worktrees\wt-e5bdcb08`)
**Python:**3.11 /3.12 /3.13
**Previous release:** v0.1.0 (2026-06-06)

---

## TL;DR

v0.2.0 turns the four modules that were skeleton-only in v0.1 (`protocols/`,
`skills/`, `web/`, `windows/`) into fully working subsystems, and ships the
first polished public surface:5 runnable examples, a tool-authoring guide,
an architecture map, the repo-root `AGENTS.md`, and a pre-tag validator
script. **No breaking changes** vs v0.1 — all CLI commands, config keys, and
public Python API are stable.

| Metric | v0.1.0 | v0.2.0 |
| --- | --- | --- |
| Passing tests | ~60 | **439** |
| Test packages |6 |12 |
| Source LOC (hello_agent) | ~3000 | ~9700 |
| Public Python modules |6 |12 |
| CLI subcommands |3 |9 |
| Examples |1 dev_bootstrap | **5 runnable + --self-test** |
| Doc pages (`docs/*.md`) |1 (ENGINEERING) |6 |

---

## Day-by-day delivery (the v0.2 plan)

The v0.2 cycle was carved into5 days. Each day's deliverable is documented
in `.mavis/plans/dayN-…-deliverable.md`.

### Day6 — MCP protocol adapters
Commit: **`7b5df3c`**

- `hello_agent/protocols/mcp_client.py` (424 LOC) — stdio JSON-RPC client
 (`list_tools`, `call_tool`, clean shutdown via `proc.terminate()`).
- `hello_agent/protocols/mcp_server.py` (175 LOC) — exposes all11 built-in
 tools as MCP tools over stdio.
- New CLI entries: `hello-agent mcp serve`, `hello-agent mcp connect`.
- `hello_agent/tools/registry.py` got `register_mcp_server()` plus a
 circuit-breaker that spans MCP calls (same protection as direct tool calls).
- Tests: `tests/test_protocols/test_mcp_client.py` + `test_mcp_server.py`
 + `test_registry_mcp_integration.py` —3 new test modules.

### Day7 — Skills system (SKILL.md loader + registry)
Commit: **`3f06edb`**

- `hello_agent/skills/loader.py` (330 LOC) — parses `SKILL.md` frontmatter
 (YAML-ish) + body sections.
- `hello_agent/skills/models.py` (309 LOC) — `Skill`, `SkillSection`,
 `SkillMetadata` dataclasses.
- `hello_agent/skills/registry.py` (515 LOC) — regex + keyword trigger
 matching with per-session activation. The ReAct agent now injects an
 `<available_skills>` block into the SYSTEM message at every turn.
-3 built-in skills under `hello_agent/skills/builtin/`:
 - `file_organize.md` — move / rename / group by date or tag
 - `daily_review.md` — Obsidian daily-note template + checklist
 - `obsidian_lookup.md` — wikilink + tag query DSL
- New CLI entries: `hello-agent skills list|show|install`.
- Tests: `tests/test_skills/test_loader.py` + `test_registry.py` +
 `test_builtin.py`.

### Day8 — Web UI (FastAPI + React + SSE)
Commit: **`14bc59b`**

- Backend: `hello_agent/web/server.py` + `routes/{chat,sessions,skills,
 tools,config}.py` — FastAPI app with SSE streaming. The chat stream emits
 typed events: `token` / `tool_call` / `tool_result` / `final`.
- Frontend: `web-ui/` — React18 + Vite5 + TypeScript. Panels: ChatPanel,
 Sidebar, SkillsPanel, MemoryPanel, ConfigPanel, ToolCallCard. State via
 nanostores; SSE consumer in `useChatStream.ts`.
- Built assets ship inside the wheel under `hello_agent/web/static/` (no
 Node.js required to run the UI after install).
- Tests: `tests/test_web/test_server.py` + `conftest.py` (FastAPI
 TestClient round-trips every route).

### Day9 — Windows integration
Commit: **`3e3edd9`**

- `hello_agent/windows/tray.py` (215 LOC) — `pystray` icon + menu
 (Show / Hide / Quit). Icon asset at `hello_agent/assets/tray.png`
 (16×16 RGBA,141 bytes).
- `hello_agent/windows/autostart.py` (197 LOC) — `HKCU\…\Run` round-trip
 with idempotent enable / disable / status.
- `hello_agent/windows/env.py` (175 LOC) — env probe, surfaced through
 `hello-agent doctor`.
- `hello_agent/windows/shortcuts.py` (104 LOC) — `.lnk` / `.url` helpers.
- New CLI entries: `hello-agent serve` (uvicorn + tray thread),
 `hello-agent autostart {enable,disable,status}`.
- Tests: `tests/test_windows/test_tray.py` + `test_autostart.py` +
 `test_env.py` — all marked `@pytest.mark.windows` and skipped on
 non-Windows platforms.

### Day10 — Examples + docs + CHANGELOG + tag
Commit: **`2b9be76`** (tag `v0.2` here)

- `examples/01_quick_chat.py` — minimal `SimpleAgent` one-liner.
- `examples/02_react_with_tools.py` — `ReActAgent` with2-3 tools.
- `examples/03_rag_index_and_query.py` — index a small corpus + query.
- `examples/04_obsidian_export.py` — write to an Obsidian vault (Windows
 junction-safe: uses `Path.resolve()` + `relative_to`).
- `examples/05_mcp_round_trip.py` — start the MCP server, connect a
 client, list & call a tool.
- Each example ships `--self-test` for offline verification (no LLM, no
 network).
- `docs/TOOL_AUTHORING.md` (393 LOC) — full worked example of writing a
 custom tool, registering it, calling it from the agent.
- `docs/ARCHITECTURE.md` (119 LOC) — v0.2 module map (ASCII).
- `AGENTS.md` at the repo root (229 LOC) — entry point for AI coding
 agents (OpenCode, Codex, Cursor, Aider, …).
- `scripts/release_check.ps1` (217 LOC) —8-gate pre-tag validator.
- `tests/test_examples.py` — subprocess-runs every example's
 `--self-test`.
- `hello_agent/__version__` bumped to `0.2.0`; `pyproject.toml` likewise.

Post-Day-10 fix-up commits (still on `wt/e5bdcb08`, ahead of tag):

- **`c69d08b`** — correct test counts in `AGENTS.md` + `CHANGELOG.md`
 (433 →439 not469).
- **`3f9f557`** — `.mavis/plans/day10-release-deliverable.md` deliverable
 report.
- **`81e7c3b`** — update deliverable with the actual push-failure status
 (sustained network outage to github.com:443; see *Known issues* below).

---

## Verification snapshot

Run on Windows PowerShell5.1, `wt/e5bdcb08` worktree at commit `81e7c3b`,
2026-06-10 ~10:00 (Asia/Shanghai):

| Gate | Command | Result |
| --- | --- | --- |
| Ruff | `uv run ruff check hello_agent/ scripts/ tests/` | **All checks passed!** |
| Pytest | `uv run pytest -q` | **439 passed in83.90s (0:01:23)** |
| Version | `uv run python -c 'import hello_agent; print(hello_agent.__version__)'` | `0.2.0` |
| pyproject.toml version | grep `^version = ` | `0.2.0` |
| Local tag `v0.2` | `git show-ref --tags` | `2b9be76d7faec0cc58c6eae1ead94ab07a0c0379 refs/tags/v0.2` |
| Remote tag `v0.2` | `git ls-remote origin refs/tags/v0.2` ×3 | **DEFERRED — see Known issues** |
| Worktree clean | `git status --porcelain` | untracked: `.mavis/plans/day10-release-decision.json` (Mavis scratchpad, not a release artifact) |
| CHANGELOG | `grep '## \[0.2.0\]' docs/CHANGELOG.md` | present |

`scripts/release_check.ps1 -Version0.2.0` could not be run end-to-end on
PowerShell5.1 due to two issues in the script itself (not in the release):

1. The auto-detect path (line84-92) reads `hello_agent/__init__.py` with
 `-Encoding UTF8`, which under PS5.1 prepends a BOM and breaks the
 `^__version__` regex. Workaround: pass `-Version0.2.0` explicitly.
2. Gate3 (line108) uses `*> $logPath` (PS7+ syntax); under PS5.1 the
 log is empty and the gate self-reports failure even when pytest
 actually passes. Direct `uv run pytest -q` succeeds.

These are script-tooling bugs, not release defects. They are filed for
follow-up in v0.3 (see *Next steps*).

---

## Known issues (release-blocking)

### Push to origin is blocked by network outage

`git push origin wt/e5bdcb08 --follow-tags` was attempted3× during the
Day10 wrap-up and again3× during this verify-and-polish session. All6
attempts failed with the same error:

```
fatal: unable to access 'https://github.com/peckerpro/minimax-agent-try-1.git/':
Failed to connect to github.com port443 after21s: Could not connect to server
```

(Sometimes `Recv failure: Connection was reset`; same root cause.)

An xray SOCKS proxy is listening on `127.0.0.1:10808`, but per the r7
post-mortem I am **not** modifying git's `http.proxy` or `http.sslverify`
without explicit user consent. Per the OWNER-SKIP convention used for
Days6 /7 /8 /9, the branch + tag remain safe locally:

- Branch `wt/e5bdcb08` is18 commits ahead of `origin/main`.
- Local tag `v0.2` is at `2b9be76` (the substantive Day10 commit).
- The full diff vs `origin/main` is **additive only** — no edits to any
 shipped v0.1 module (`agents/`, `tools/`, `rag/`, `context/`, `memory/`
 are byte-identical to v0.1.0).

**User action required:** once github.com:443 is reachable, push manually:

```powershell
git push origin wt/e5bdcb08 --follow-tags
```

---

## What's new for users (in60 seconds)

If you used v0.1, the things you can do *today* that you couldn't *yesterday*:

1. **Spin up a Web UI.** `uv run hello-agent serve` opens a browser with
 a chat panel that streams tokens + tool calls live over SSE. No more
 CLI-only.
2. **Run a tray app on Windows.** `uv run hello-agent serve` also drops
 a `pystray` icon in the notification area with Show / Hide / Quit.
 `uv run hello-agent autostart enable` registers it on login.
3. **Talk to an MCP server.** `uv run hello-agent mcp serve` exposes all
11 built-in tools to any MCP-compatible client (e.g. Claude Desktop).
 Conversely, `uv run hello-agent mcp connect` lets the agent call
 external MCP servers.
4. **Use packaged skills.** The agent now reads `SKILL.md` files and
 injects their procedural guidance into the SYSTEM prompt when the
 user's prompt matches a skill's triggers. Try
 `uv run hello-agent skills list`.
5. **Copy an example and modify it.** `examples/01..05` cover quick-chat,
 ReAct, RAG, Obsidian export, and an MCP round-trip. Each has
 `--self-test` so the verifier can run it offline.

---

## Breaking changes

**None.** All v0.1 public surface is preserved:

- All CLI commands from v0.1 (`hello-agent`, `hello-agent chat`,
 `hello-agent doctor`) are unchanged.
- All config keys in `config.yaml` are unchanged.
- All public Python API (`hello_agent.SimpleAgent`, `hello_agent.ReActAgent`,
 `hello_agent.tools.registry`, …) is unchanged.
- New CLI commands (`serve`, `autostart`, `skills`, `mcp`) are purely
 additive.

If you pinned v0.1 with `~=0.1`, **no migration is needed**.

---

## Files changed in this cycle

`git diff f5f05fc^..HEAD --stat` (10 commits,18 ahead of `origin/main`):

```
101 files changed,15779 insertions(+),53 deletions(-)
```

Top-level additions:

- New source packages: `hello_agent/protocols/`, `hello_agent/skills/`,
 `hello_agent/web/`, `hello_agent/windows/`.
- New test packages: `tests/test_protocols/`, `tests/test_skills/`,
 `tests/test_web/`, `tests/test_windows/`, `tests/test_examples.py`.
- New docs: `docs/TOOL_AUTHORING.md`, `docs/ARCHITECTURE.md`, `docs/v0.2-PLAN.md`.
- New examples: `examples/01..05` (5 files) + `examples/__init__.py`.
- New web UI: `web-ui/` (React18 + Vite5 + TS,27 files).
- Repo root: `AGENTS.md`.
- Scripts: `scripts/release_check.ps1`, `scripts/smoke_skills.py`.

---

## Commit map

```
81e7c3b docs(day10): update deliverable with actual push-failure status
3f9f557 docs(day10): deliverable report
c69d08b docs(day10): correct test counts (433 →439)
2b9be76 docs(day10): examples + TOOL_AUTHORING + CHANGELOG + AGENTS.md + tag v0.2
499d964 docs(day9): deliverable report
3e3edd9 feat(day9): Windows tray + autostart + serve + env probe
14bc59b feat(day8): Web UI (FastAPI + React + SSE)
3f06edb feat(day7): SKILL.md loader + registry +3 builtins
7b5df3c feat(day6): MCP client + server (stdio JSON-RPC, registry routing)
f5f05fc docs: v0.2-PLAN + v0.2.yaml (5-day delivery contract)
```

The local `v0.2` tag points at `2b9be76` (the substantive Day10 commit).
The3 follow-up commits (`c69d08b`, `3f9f557`, `81e7c3b`) are doc-only
fix-ups and post-Day-10 status updates; they are intentionally NOT part of
the `v0.2` tag — moving the tag forward would invalidate the CHANGELOG
example count claim at `2b9be76`.

---

## Next steps (v0.3 follow-on)

1. **Push.** Once github.com:443 is reachable, push
 `wt/e5bdcb08 --follow-tags` so the `v0.2` tag is on origin.
2. **Fix `scripts/release_check.ps1` for PowerShell5.1.** BOM-strip on
 version auto-detect; replace `*>` with `2>&1 | Out-File` (or require
 PS7+ explicitly).
3. **Add `.mavis/` to `.gitignore`.** It currently pollutes
 `git status --porcelain`. Low-risk, additive.
4. **Move `AGENTS.md` test count claim from439 →442** if v0.3 adds the
 MCP integration test that was deferred (Day6 follow-up #2).
5. **Wire the MCP client into the agent loop.** Today the agent must be
 told explicitly which MCP server to call; in v0.3 we want auto-routing
 by tool name.

---

## Credits

v0.2 was delivered by the Mavis team-plan "hello-agent-2 v0.2" cycle
(`.mavis/plans/v0.2.yaml`), with one producer session per day (Day6 →
Day10) and a verify-and-polish session (this one) wrapping the cycle.
Day10 used the OWNER-SKIP / OWNER-RECOVERED pattern: the producer hit
the30-minute hard cap during wrap-up *after* the substantive commit
(`2b9be76`) and the local `v0.2` tag were on disk, so the owner
re-derived the13 verifier checks in-session and committed the rest as
`c69d08b` / `3f9f557` / `81e7c3b`.
