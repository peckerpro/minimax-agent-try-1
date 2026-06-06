# Day 4 — Context Engineering + Memory — Final Report

**Producer:** coder (mvs_0ff73b60362340a4add3c4f790210c7e)
**Branch:** `wt/e5bdcb08`
**Local commit:** `52e62dc feat(day4): context engineering + short/long/episodic memory`
**Push status:** **KNOWN-FAILED** — Dr.COM captive portal blocks TCP 443 to github.com.
Parent will retry the push + override_accept when the network is restored.

## What shipped

### A. `hello_agent/context/` (modified to Day-4 spec)
- `history.py` — flag-aware `HistoryManager`. `max_messages=50` from `config.memory.short_term_max_messages`. `mark_compressed` / `mark_truncated` helpers. Compressed digests are **never** evicted by the sliding window.
- `token_counter.py` — new `TokenCounter` class with `use_tiktoken` flag. Falls back to **chars/4** heuristic when tiktoken is unavailable. Cached encoding for repeated calls. `count` / `count_text` / `fits` / `head_room`. Module-level `count_tokens` / `count_text_tokens` shims preserved.
- `truncator.py` — new `ObservationTruncator(strategy, head_lines, tail_lines)` class. Defaults read from `config.context.truncator_*`. Three strategies: `head_tail` (default), `middle_out`, `summarize` (v0.1 → falls back to `head_tail`). Returns a *new* `Message` with `truncated=True`. Module-level `truncate` shim preserved.
- `builder.py` — new `ContextBuilder(max_context_tokens, response_reserve_tokens, truncator)`. Defaults: 128_000 / 4_000 from `config.context`. Order: system → memory chunks (with `cache_breakpoint=True`) → past messages → RAG chunks. **Budget enforcement** in two stages: (1) truncate long tool outputs, (2) drop oldest non-system, non-compressed messages. System message always survives. Module-level `build_prompt` shim preserved.

### B. `hello_agent/memory/` (new)
- `short_term.py` — `ShortTermMemory(history + facts dict + persist())`. `add_fact` / `get_fact` / `list_facts` / `remove_fact` per §6.6. `persist(long_term)` pushes facts to the long-term store with a `_persisted_keys` set so re-pushing is a no-op.
- `long_term.py` — `LongTermMemory` over stdlib `sqlite3` (no ORM). Schema: **`facts(id, key, value, source, created_at, updated_at)`** with `UNIQUE(key)` for upsert + indexes on `source` and `key`. Default path: `~/.hello-agent/memory/long_term.db` (per `config.yaml`). JSON-encoded values (so string `"1"` round-trips to string `"1"`, not int `1`). WAL journaling. Context-manager protocol. `set_fact` / `get_fact` / `get_fact_row` / `delete_fact` / `list_facts` / `search` / `count` / `transaction`.
- `episodic.py` — `EpisodicMemory` over stdlib `sqlite3`. Schema: **`episodes(id, session_id, summary, created_at)`**. Shares the long-term sqlite file. `summarize_every_n_turns=20` from `config.memory.episodic_summarize_every_n_turns`. `record_episode` / `list_recent` / `search` / `count` / `should_summarize(n)` trigger.

### C. `scripts/smoke_context.py` (new)
6 sections, all green:
1. `TokenCounter` (3 messages = 21 tokens; heuristic `a`*40 = 10; module-level matches class)
2. `HistoryManager` sliding window (60→50, system survives, compressed survives)
3. `ObservationTruncator.head_tail` on 1000-line string (head 10 / marker / tail 5 = 18 splitlines)
4. `ContextBuilder` end-to-end (system + history; memory chunks with `cache_breakpoint`; RAG chunks; budget trim 20→3)
5. `LongTermMemory` SQLite round-trip (set/get string, int, dict; upsert; list+source filter; search; delete; transaction commit/rollback; context manager)
6. `EpisodicMemory` SQLite round-trip (`should_summarize(20|40)` true; record+list; session_id filter; search)

### D. `tests/test_context/` + `tests/test_memory/` (new)
- `tests/test_context/test_history.py` (14 tests) — sliding window, system survival, compressed survival, flag helpers, clear/replace/set_system, iteration, indexing.
- `tests/test_context/test_token_counter.py` (12 tests) — class + module, heuristic path, fits/head_room, tool-call args.
- `tests/test_context/test_truncator.py` (10 tests) — all 3 strategies, flag, no-op for short, module shim.
- `tests/test_context/test_builder.py` (12 tests) — order, memory/rag chunks, budget enforcement, compressed preservation, state immutability, module shim.
- `tests/test_memory/test_long_term.py` (19 tests) — CRUD, upsert, list/search/count, delete, transaction commit/rollback, context manager, default path resolution.
- `tests/test_memory/test_episodic.py` (14 tests) — record+list, ordering, session filter, search, count, `should_summarize`, input validation, transaction.
- `tests/test_memory/test_short_term.py` (11 tests) — fact API, history delegation, clear, persist.

### `hello_agent/core/types.py` (modified)
Added per-message flags: `compressed`, `truncated`, `cache_breakpoint`, `system` (derived from `role`), `tool` (derived from `role`). `__post_init__` mirrors `system`/`tool` from `role` by default; callers can override. `from_dict` is tolerant of older serialized dicts (sets defaults for missing fields) — back-compat with Day 1-3 persisted state.

## Verification

| Check | Result |
|-------|--------|
| `uv run ruff check .` | **All checks passed!** ✅ |
| `uv run pytest -q` (full suite) | **215 passed** in 7.08s ✅ (was 120, **+95 new** Day 4 tests) |
| `uv run pytest tests/test_context tests/test_memory -q` | 95 passed in 1.17s ✅ |
| `uv run python scripts/smoke_context.py` | **[smoke_context] OK: all 6 sections passed** ✅ |
| `uv run python scripts/smoke_agents.py` | 5/5 sections passed ✅ (Day 3) |
| `uv run python scripts/smoke_tools.py`  | 6/6 sections passed ✅ (Day 2) |
| `uv run python scripts/smoke_core.py`   | SKIP (no LLM_API_KEY) ✅ (Day 1) |
| `uv run python scripts/smoke_cli.py`    | OK ✅ (Day 1) |
| Day 1-3 still green | ✅ confirmed via the 215-test suite (no regressions) |
| Local commit on `wt/e5bdcb08` | `52e62dc` ✅ |
| `git push origin wt/e5bdcb08` | **KNOWN-FAILED** — Dr.COM captive portal blocks TCP 443. **Parent to retry + override_accept.** |

## Item-10 push status (KNOWN-FAILED)

```
$ git push origin wt/e5bdcb08
fatal: unable to access 'https://github.com/peckerpro/minimax-agent-try-1.git/':
Failed to connect to github.com port 443 after 21093 ms: Could not connect to server
```

Confirmed by parent: this is a Dr.COM captive-portal 443 block, not transient.
**Local commit `52e62dc` exists on `wt/e5bdcb08`** and is the canonical Day 4
artifact — `git log --oneline -3` shows it on top of `87d94d8` (Day 3). The
parent will handle the push + override_accept once the network is restored.
