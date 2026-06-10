# Day 10 — v0.2 release deliverable

> **Status:** v0.2 released locally on `wt/e5bdcb08` (HEAD `c69d08b`, 17 commits
> ahead of `origin/main`). Local `v0.2` tag points at `2b9be76`. Push to
> `origin/wt/e5bdcb08` and `--follow-tags` push of `v0.2` attempted; see
> "Push status" below.

## What shipped (Day 10 — release)

### A. `examples/` — 5 runnable scripts

| File | Purpose | `--self-test` |
| --- | --- | --- |
| `examples/01_quick_chat.py` | 10-line `LLMClient + SimpleAgent.chat("hello")` | OK (3 msgs, last = "SimpleAgent would call the LLM with: 'hello'") |
| `examples/02_react_with_tools.py` | `ReActAgent + file_tools.read_file` round-trip | OK (2 iters, 1 tool dispatch, final = "[self-test] read_file complete") |
| `examples/03_rag_index_and_query.py` | Walk a dir, index with chromadb, query via retrieval ensemble | OK (2 files / 2 chunks indexed; `retrieve()` returned 2 results) |
| `examples/04_obsidian_export.py` | `LongTermMemory.add_fact` + `ObsidianSync.export_memory` | OK (wrote `2026-06-10_favorite-editor.md`; `list_memories()` saw 1 file) |
| `examples/05_mcp_round_trip.py` | Spawn hello-agent as MCP server, connect from a second as MCP client, exchange one tool call | OK (round-trip in 3.92s; server advertised 11 tools) |

All 5 examples support `--self-test` and run **without** an LLM API key —
they stub the LLM and exercise the relevant code paths.

### B. Docs

| File | Status | Notes |
| --- | --- | --- |
| `docs/TOOL_AUTHORING.md` | NEW (393 lines) | Step-by-step: `@tool` decorator, register, test, distribute as plugin; one full worked example |
| `docs/CHANGELOG.md` | UPDATED | v0.2.0 entry: 5 days (MCP / Skills / Web UI / Windows / examples+docs), file list, test count, no breaking changes |
| `AGENTS.md` | NEW (229 lines, repo root) | Per `docs/ENGINEERING.md` §10 hint — build/test/lint commands, day-by-day plan, layering rules, "what NOT to do" |
| `docs/ARCHITECTURE.md` | NEW (119 lines) | ASCII module map `core → agents → tools → memory → rag → protocols (MCP) → web` |
| `README.md` | UPDATED | v0.2 status table; quick-start for `hello-agent serve` |

### C. Version + README

- `hello_agent/__init__.py` — `__version__ = "0.2.0"`
- `pyproject.toml` — `version = "0.2.0"` (matches)
- `README.md` — v0.2 status table; Days 1-10 all listed as shipped

### D. Tests

- `tests/test_examples.py` (NEW, 6 tests, 79 lines) — subprocess-runs every
  example with `--self-test`; asserts exit 0. Asserts the `examples/`
  directory contains exactly 5 runnable scripts.
- `tests/test_cli/test_version.py` (FIXED) — was hardcoded `v0.1.0`, now
  reads `hello_agent.__version__` so future bumps don't break this test.

### E. Release script

- `scripts/release_check.ps1` (NEW, 217 lines) — pre-tag validator:
  - `uv run ruff check hello_agent/ scripts/ tests/`
  - `uv run pytest -q` (full suite)
  - `uv run python -c "import hello_agent; assert hello_agent.__version__ == '<expected>'"`
  - `git tag -l <tag>` does not already exist (refuses to over-tag)

## Verifier re-check (re-derived in this session — owner-recovered)

| # | Check | Result |
| --- | --- | --- |
| 1 | All §A / §B / §C / §D / §E files exist with non-empty content | PASS — see table above |
| 2 | No regression in v0.1 + Day 6-9 | PASS — `from hello_agent.windows import tray, autostart; from hello_agent.web import server; from hello_agent.skills import loader; from hello_agent.protocols import mcp_client` all import cleanly |
| 3 | Examples' `--self-test` works | PASS — 5/5 (see table A) |
| 4 | `tests/test_examples.py` | PASS — 6/6 in 14.02s |
| 5 | Full suite | PASS — **439 passed in 94.28s** (was 433 after Day 9; +6 example tests) |
| 6 | Ruff | PASS — `All checks passed!` |
| 7 | Day 1-9 still green | PASS — `tests/test_web/ tests/test_protocols/ tests/test_skills/ tests/test_windows/` → 162 passed in 63.43s |
| 8 | Version | PASS — `0.2.0` |
| 9 | Local tag `v0.2` | PASS — points at `2b9be76` (Day 10 commit) |
| 10 | Tag pushed to origin | **PUSH RETRY (see below)** |
| 11 | Final report exists | PASS — this file |
| 12 | ENGINEERING.md §3 directory tree match | PASS — `hello_agent/` has all 12 sub-packages: `core/`, `agents/`, `tools/` (with `builtin/`), `context/`, `memory/`, `rag/`, `protocols/`, `web/`, `windows/`, `skills/`, `observability/`, `cli/` |
| 13 | Examples --self-test on this machine | PASS — all 5/5 (no missing optional deps) |

## Recovery context (OWNER-SKIP)

This deliverable was recovered by the owner (Mavis) directly after the
Day 10 producer session was killed by the 30-min hard cap during wrap-up.
The producer completed:

- **Substantive work:** 18 files / 1943 insertions committed at `2b9be76`
  (5 examples, 4 docs, AGENTS.md, release_check.ps1, test_examples.py,
  version bumps, 2 fixes).
- **Local tag:** `v0.2` created and pointing at `2b9be76`.

What was NOT done before the kill:

- **Deliverable doc** (this file) — producer's last action was a doc-fix
  rebase attempt that left AGENTS.md / CHANGELOG.md with uncommitted
  corrections (test count 469 → 439). Owner committed those as
  `c69d08b` before writing this report.
- **Push to origin** — Day 9 push succeeded, but Day 10 push (`2b9be76`
  + `c69d08b`) hit the same github.com:443 network instability that
  affected Day 8. Owner retried push with `--follow-tags` — see below.
- **Independent verifier step** — skipped per the OWNER-SKIP convention
  used for Day 6 / 7 / 8 / 9; the owner re-derived all 13 verifier
  checks in this session.

## Push status

```
$ git push origin wt/e5bdcb08 --follow-tags
```

First attempt: `Recv failure: Connection was reset` (Day 8 pattern).
Retried 2 more times with 5s sleep. Per memory (`Git push from this
Windows box — retry 2-3 times for transient TCP resets`), attempt 3
is expected to succeed. **Push result depends on network state at the
moment of the next session.** The commits and tag are safe locally on
`wt/e5bdcb08` at `c69d08b` / `2b9be76`; the user can push manually
(`git push origin wt/e5bdcb08 --follow-tags`) whenever the proxy /
network recovers.

If the push ultimately succeeds:

```
$ git ls-remote origin refs/tags/v0.2
<sha>    refs/tags/v0.2
```

That SHA must equal `git rev-list -n1 v0.2` → `2b9be76d7faec0cc58c6eae1ead94ab07a0c0379`.

## Git log at end of Day 10 (local)

```
c69d08b docs(day10): correct test counts in AGENTS.md + CHANGELOG.md (433 → 439 not 469)
2b9be76 docs(day10): examples + TOOL_AUTHORING + CHANGELOG v0.2.0 + AGENTS.md + tag v0.2
499d964 docs(day9): deliverable report (tray + autostart + serve + env probe; 433 tests green)
3e3edd9 feat(day9): Windows tray + autostart + serve entry + env probe
14bc59b feat(day8): Web UI (FastAPI + React + SSE streaming + skills/tools/config panels)
3f06edb feat(day7): SKILL.md loader + registry + 3 builtins (file_organize / daily_review / obsidian_lookup)
7b5df3c feat(day6): MCP client + server (stdio JSON-RPC, registry routing)
f5f05fc docs: v0.2-PLAN + v0.2.yaml (5-day MCP+Skills+Web+Windows+release)
b7ae399 chore(day5): remove extra blank line in smoke_rag to satisfy ruff I001
2bee8f3 feat(day5): RAG (chromadb 4 strategies) + Obsidian/Git sync scaffolds
52e62dc feat(day4): context engineering + short/long/episodic memory
87d94d8 feat(day3): ReAct / PlanAndSolve / Reflection agents + TaskRouter + CLI run expansion
8d09427 feat(day2): tool registry + circuit breaker + builtin document/file/shell tools
2ee12fd chore(plan): relax scope-creep check + auto_accept + extra retry
8d88030 feat(day1): core abstractions + SimpleAgent + CLI chat scaffold
```

17 commits on `wt/e5bdcb08` ahead of `origin/main`.

## What's left for v0.3 (5-line note)

1. **v0.2 push cleanup** — once the github.com:443 network is stable,
   push the local 17 commits and `v0.2` tag. Optionally delete and
   recreate `v0.2` if any local hash drifted.
2. **CI integration** — wire `scripts/release_check.ps1` into a
   GitHub Actions workflow so the v0.2 release was actually gated.
3. **Frontend polish** — the v0.2 React UI is functional but minimal;
   add real-time tool-call rendering for SSE token streams, drag-drop
   file upload for the skills installer, and a memory graph view.
4. **MCP marketplace** — the v0.2 MCP server exposes all 11 built-in
   tools, but a registry / discovery layer for community-contributed
   MCP servers is v0.3 scope.
5. **Windows hotkey** — `windows/shortcuts.py` is stubbed (stretch
   goal from Day 9 that didn't ship); wire the global hotkey to
   "show chat panel" and document the per-process permissions.