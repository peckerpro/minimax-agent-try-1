# Day 2 — Tooling deliverable

> hello-agent-2 v0.1, worktree `wt/e5bdcb08` · commit `8d09427` · pushed to `origin/wt/e5bdcb08`

## 1. Summary

Day 2 added the missing day-2-spec surface to the tool system that Day 1
already scaffolded (`base.py`, `registry.py`, `response.py`, `circuit_breaker.py`,
`permission.py`, all 8 builtin tools), wrote the day-2 smoke harness, and
filled the empty `tests/test_tools/` tree with five focused test files.

The new spec bits that didn't yet exist are now in place:
`ToolRegistry.unregister() / list() / filter_by_profile() / auto_discover`,
`CircuitBreaker.failure_threshold / reset_timeout_ms` aliases,
`ToolRegistry._register.register_all(target=None)` for non-singleton
registration, and a Windows-safe byte-literal fix on `_atomic_write` so the
file tools round-trip `\n` literally instead of going through `\r\n`.

## 2. Verification

All four acceptance criteria pass on this worktree:

| Check | Command | Result |
|---|---|---|
| 2. ruff | `uv run ruff check hello_agent/ scripts/ tests/` | `All checks passed!` (exit 0) |
| 3. smoke | `uv run python scripts/smoke_tools.py` | `OK: all 6 sections passed` (exit 0) |
| 4. pytest | `uv run pytest tests/test_tools/ -q` | `50 passed in 2.54s` (exit 0) |
| 5. push | `git push origin wt/e5bdcb08` | `2ee12fd..8d09427  wt/e5bdcb08 -> wt/e5bdcb08` |
| (extra) full suite | `uv run pytest -q` | `69 passed in 5.62s` — no regressions |

Smoke harness (the 6 sections from §C of the task):
1. `ToolRegistry.register / get / list` round-trip on a fresh registry
2. `ToolResponse` shape (`ok` / `fail` / `to_json`)
3. `CircuitBreaker` state transitions (closed → open → half_open → closed, plus re-open)
4. `document_parser` fallback chain (raw for .md, force_parser override, missing path)
5. `file_tools.read_file / write_file / edit_file` round-trip on a tmp file
6. `shell_tool.run_cmd "echo hello"` (asserts `hello` in stdout, `returncode == 0`)

Pytest counts in `tests/test_tools/` (5 files, 50 tests total — well over the ≥ 5 minimum):

| File | Tests | Coverage |
|---|---|---|
| `test_response.py` | 6 | ToolResponse re-export, `ok`/`fail`/`from_exception`/`to_json`, non-JSON data |
| `test_circuit_breaker.py` | 11 | closed→open, open→half_open, half_open→closed, half_open→open, per-tool isolation, window reset, day-2 alias kwargs, module-level singleton helpers |
| `test_registry.py` | 18 | register/get/list, dangerous flag, unregister (incl. session-confirmation clearing + toolset membership), `list` alias, `filter_by_profile` (by toolset, by register_toolset, unknown profile, `enabled_only`), execute (handler call, disabled block, dangerous confirmation), `auto_discover` off / on |
| `test_file_tools.py` | 9 | round-trip byte-literal, parent-dir creation, truncation, missing file, path-traversal guard, edit single occurrence, edit ambiguous, edit missing-old, edit missing file |
| `test_shell_tool.py` | 6 | echo hello, non-zero exit code captured, empty command rejected, max_bytes truncation, PowerShell on Windows, Python-on-PATH probe |
| **Total** | **50** | |

## 3. Changed files

### Created
- `scripts/smoke_tools.py` — 6-section smoke harness (per §C of the day-2 task)
- `tests/test_tools/__init__.py` — empty package marker
- `tests/test_tools/test_response.py` — 6 tests for `ToolResponse`
- `tests/test_tools/test_circuit_breaker.py` — 11 tests for `CircuitBreaker`
- `tests/test_tools/test_registry.py` — 18 tests for `ToolRegistry`
- `tests/test_tools/test_file_tools.py` — 9 tests for `read/write/edit_file`
- `tests/test_tools/test_shell_tool.py` — 6 tests for `run_cmd` / `run_powershell`

### Modified
- `hello_agent/tools/registry.py`
  - `__init__(auto_discover=False)` — new keyword-only flag
  - `auto_discover()` — new method; calls `register_all(self)` once
  - `unregister(name)` — new; drops from `_tools`, `_toolsets[entry.toolset]`,
    `_enabled`, `_disabled`, and every per-session confirmation cache
  - `list` — new class attribute alias for `list_all()` (spec name)
  - `filter_by_profile(profile, enabled_only=False)` — new; resolves
    toolset-name or `toolset == profile`, dedupes, optionally filters disabled
  - logger import added (`logging` stdlib, not loguru) for the debug path
- `hello_agent/tools/builtin/_register.py`
  - `register_all(target: ToolRegistry | None = None)` — now takes an optional
    target registry; default still falls back to the shared singleton for
    backward compat
  - imports moved out of the function body (top-level) for a cleaner module
- `hello_agent/tools/circuit_breaker.py`
  - `__init__` now accepts two keyword-only aliases for the day-2 spec names:
    `failure_threshold` (== `fail_threshold`) and `reset_timeout_ms`
    (== `cooldown_seconds * 1000`)
  - read-only `failure_threshold` and `reset_timeout_ms` properties
- `hello_agent/tools/builtin/file_tools.py`
  - `_atomic_write` now opens with `newline=""` — Windows text-mode no
    longer translates `\n` to `\r\n` on the way to disk. Byte-literal
    round-trip is part of the contract of the file tools.

## 4. Notes for the verifier

1. **Day 1 already shipped most of §A and §B.** When I started Day 2 the
   `hello_agent/tools/` tree already had `base.py`, `registry.py`, `response.py`,
   `circuit_breaker.py`, `permission.py`, `toolsets.py`, and all 8 builtin tools
   (including `document_parser`, `file_tools`, `shell_tool`). The day-2
   additions are therefore the spec surface that Day 1 didn't have
   (`unregister` / `list` / `filter_by_profile` / `auto_discover` / alias kwargs)
   plus the smoke script and the test tree.

2. **No pyproject.toml dep changes.** Smoke + tests use only what Day 1 already
   pinned (`openai`, `httpx`, `pydantic`, `pydantic-settings`, `loguru`,
   `pyyaml`, `python-dotenv`, `typer`, `tiktoken`, `python-frontmatter`,
   `tzdata`). The optional `markitdown` / `pypdf` deps that `document_parser`
   needs at runtime are already declared in `[project.optional-dependencies]`.

3. **`markitdown` is installed in this venv.** Section 4 of the smoke takes
   advantage of that — the .pdf smoke uses the `markitdown` parser
   successfully. If you re-run on a fresh venv that does NOT have
   `markitdown` / `pypdf` / `MinerU`, the smoke still passes (it checks both
   branches: success via `markitdown`, OR `All parsers failed` with the hint
   populated). The markdown-only branch is parser-agnostic and works
   everywhere because `_parse_raw` is built-in.

4. **One pre-existing bug found and fixed.** `file_tools._atomic_write` opened
   the tempfile in default text mode on Windows, which translates `\n` →
   `\r\n` on write. The byte-literal round-trip test caught this. Fixed by
   passing `newline=""` to `os.fdopen`. After the fix, the round-trip is
   byte-literal (verified by the smoke and the new test).

5. **One pre-existing test bug found and fixed.** My first draft of
   `test_module_level_singleton_helpers_round_trip` had a `while check_breaker():
   record_success()` loop that was a no-op on a fresh slot (because a fresh
   slot is already closed and `allow()` returns True, so the loop never
   terminates). Replaced with a simple "record_success once, then proceed"
   pattern. All 11 circuit-breaker tests now pass in <1s.

6. **Commit + push are on `wt/e5bdcb08`.** Single commit `8d09427` carries
   all 11 changed files (+1192 / -26 lines). Branch is now at
   `2ee12fd..8d09427` ahead of the previous tip. `git log --oneline -3`
   should show:
   ```
   8d09427 feat(day2): tool registry + circuit breaker + builtin document/file/shell tools
   2ee12fd chore(plan): relax scope-creep check + auto_accept + extra retry
   8d88030 feat(day1): core abstractions + SimpleAgent + CLI chat scaffold
   ```

7. **Worktree's `.mavis/` directory is intentionally uncommitted** (matches
   `.gitignore` patterns used elsewhere — it's per-machine session state).
