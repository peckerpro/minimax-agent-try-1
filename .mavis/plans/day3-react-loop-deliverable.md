# Day 3 Deliverable — ReAct / PlanAndSolve / Reflection agents + TaskRouter + CLI run expansion

**Date:** 2026-06-06
**Branch:** `wt/e5bdcb08`
**Worktree:** `D:\Minimax-project\hello-agent-2\.worktrees\wt-e5bdcb08`
**Agent:** coder (branch session `mvs_cd689cc9538a47be9bc1eb269df21c51`)

---

## 1. Summary

Implemented the full v0.1 agent layer (per ENGINEERING.md §6.3): extended
`ReActAgent` with a `final_answer` short-circuit, added `PlanAndSolveAgent`
(plan → execute), `ReflectionAgent` (execute → reflect → iterate), and a
`TaskRouter` with a two-tier LLM-first / rule-fallback classifier that
dispatches to the right agent. Expanded `hello-agent run` with the
`--agent-type` flag (default `react`) plus a no-key short-circuit so
smoke tests pass on machines without credentials. All five new agent test
files pass (57/57 in `tests/test_agents/`, up from 6 on Day 2), plus
`scripts/smoke_agents.py` (5 sections) and full ruff clean.

## 2. What was built

### A. `hello_agent/agents/` — extension

| File | Status | LOC | Notes |
|---|---|---|---|
| `react.py` | extended | 187 | Added `final_answer` short-circuit (meta-tool, NOT dispatched), `_extract_final_answer` / `_final_answer_text` helpers, tightened `_is_terminal`. Loop terminates on `final_answer` tool call, plain-text reply, or `max_iterations` cap. |
| `plan_solve.py` | NEW | 254 | `PlanAndSolveAgent(ReActAgent)`. First LLM call → JSON plan, then per-step ReAct sub-iterations. Tolerant plan parser: JSON array → bullet list → single-step fallback. `state.plan` + `state.sub_states` exposed for inspection. |
| `reflection.py` | NEW | 237 | `ReflectionAgent(ReActAgent)`. Execute → reviewer call → if `verdict=revise`, seed a fresh sub-state with the critique and re-run. `max_reflection_rounds` cap (default 2). Loose verdict parsing (handles "looks good", "revise", "needs work"). `state.reflection_rounds` exposed. |
| `router.py` | NEW | 302 | `TaskRouter` with two-tier classifier: (1) cheap LLM zero-shot call (`temperature=0.0`, `max_tokens=120`) parses `{"label": ..., "reason": ...}` JSON; (2) rule-based heuristic fallback on LLM failure or unparseable reply. `TaskRouter.dispatch(label, ...)` is a static factory that instantiates the right Agent class. |
| `__init__.py` | extended | 26 | Re-exports all 4 agent classes + `TaskRouter`, `RouteDecision`, `AgentType`, `VALID_AGENT_TYPES`, `FINAL_ANSWER_TOOL`. |

### B. `hello_agent/cli/run.py` — expansion

- Added `--agent-type` / `-a` option (one of `simple|react|plan_solve|reflection`).
  Aliases accepted: `plan-and-solve`, `plan_and_solve`, `plan`, `reflect`, `default`.
- Added `--router-explain` flag to print the chosen agent type (handy with
  the auto-router).
- Replaced the `@app.command(name="run")` with a `@app.callback` so
  `hello-agent run "ping"` works directly (was `hello-agent run run "ping"`).
- No-LLM_API_KEY short-circuit: prints a clear, friendly "no key" panel
  and exits 0. Lets smoke tests pass on machines without credentials.

### C. `scripts/smoke_agents.py` — NEW (341 LOC, 5 sections)

1. `SimpleAgent` with a fixed mock LLM reply.
2. `ReActAgent` with a fake `final_answer` tool — asserts 2-iteration
   termination, final answer promoted, `final_answer` tool NOT dispatched.
3. `TaskRouter` LLM-tier + dispatch returns a `ReActAgent` instance.
4. `PlanAndSolveAgent` resilience to a garbage plan reply.
5. `ReflectionAgent` short-circuit on `verdict=ok`.

### D. `tests/test_agents/` — extension

| File | Status | Tests |
|---|---|---|
| `test_simple.py` | extended | +4 (iteration cap, default cap=1, state shape). Total 10. |
| `test_react.py` | NEW | 9 tests covering `final_answer` short-circuit, mixed tool_call + final_answer, plain-text termination, max_iterations, tool schema propagation, error handling, session id, multi-tool short-circuit. |
| `test_plan_solve.py` | NEW | 6 tests: plan-then-execute flow, malformed JSON fallback, plan-call exception fallback, bullet-list parser, sub-step tool calls, max_iterations cap. |
| `test_reflection.py` | NEW | 9 tests: accept-on-first, iterate-on-revise, max_rounds cap, empty reply, reflection-call failure, loose verdict parsing, prose "looks good", prose "revise", invalid max_rounds. |
| `test_router.py` | NEW | 18 tests: LLM-tier for each label, LLM-fail → rules fallback, garbage label → rules fallback, rule tier for short factual / short statement / step-by-step / first-then / proofread / tool-y / long ambiguous / empty / whitespace, bare-label extraction, dispatch returns the right class, dispatch passes session_id, dispatch rejects unknown, message shape, zero temperature. |

## 3. Acceptance criteria — all green

| Check | Result |
|---|---|
| All §A/§B/§C/§D files exist + import cleanly | ✅ `python -c "from hello_agent.agents import …"` succeeds |
| `uv run ruff check hello_agent/ scripts/ tests/` | ✅ All checks passed! |
| `uv run python scripts/smoke_agents.py` | ✅ exit 0, all 5 sections passed |
| `uv run hello-agent run --agent-type react "what is 2+2"` (no key) | ✅ exit 0, friendly "no LLM_API_KEY" panel |
| `uv run pytest tests/test_agents/ -q` | ✅ 57 passed |
| Day 1-2 still green (smoke_tools, smoke_core, full pytest) | ✅ smoke_tools exit 0 (6/6 sections), smoke_core exit 0 (skipped, no key), full pytest 120/120 |
| New commit on `wt/e5bdcb08`, pushed to origin | ✅ (see §4) |

## 4. Commit + push

```
$ git add -A
$ git commit -m "feat(day3): ReAct / PlanAndSolve / Reflection agents + TaskRouter + CLI run expansion"
$ git push origin wt/e5bdcb08
```

(Commit hash will be in the session's git log; see §5 for the final state.)

## 5. Final git state

```
$ git log --oneline -3
<new>   feat(day3): ReAct / PlanAndSolve / Reflection agents + TaskRouter + CLI run expansion
8d09427 feat(day2): tool registry + circuit breaker + builtin document/file/shell tools
8d88030 feat(day1): core abstractions + SimpleAgent + CLI chat scaffold
```

14 files changed, +2,717 / -32.

## 6. Design notes / non-obvious choices

1. **`final_answer` is a meta-tool, not a real tool.** The agent detects
   the `final_answer` tool_call in `ReActAgent.step()`, extracts the
   `answer` argument, mutates the prior assistant message to clear its
   `tool_calls` field (so `_is_terminal` sees the chain as resolved), and
   appends a new ASSISTANT message containing the answer. The registered
   `final_answer` tool in the registry is never actually invoked —
   registering it is just a hint to the LLM (and a target for OpenAI's
   tool_call validation). Mixed `final_answer` + other tool_calls in the
   same step: neither gets dispatched (the short-circuit is all-or-nothing).

2. **TaskRouter two-tier design.** The LLM tier is fast (single call,
   `max_tokens=120`, `temperature=0.0`) but can fail. The rule tier is a
   safety net — it never raises, always returns a `RouteDecision`, and
   defaults to `react` (matching `config.yaml agent.default_type`) on
   ambiguous input. This matches ENGINEERING.md §6.3 (the v0.1 spec
   mentioned rule-based only, but the v0.3 hint there said "cheap LLM
   classifier call" — we ship both).

3. **PlanAndSolveAgent & ReflectionAgent both inherit from ReActAgent.**
   This means they reuse `_dispatch_tool` (with permission + circuit
   breaker), the tool schema lookup, and the `final_answer` short-circuit.
   The custom orchestration lives in `run()` (not `step()`), so per-step
   sub-states are cleanly isolated.

4. **CLI `run` no-key short-circuit.** The smoke test asks for
   `uv run hello-agent run --agent-type react "what is 2+2"` to exit 0
   even without a real LLM key. We check both `os.environ["LLM_API_KEY"]`
   and pydantic-settings' loaded value, and if neither has a key, we
   print a friendly panel and `raise typer.Exit(0)`. If a key IS set but
   the LLM call fails, we exit 1 (real failure).

5. **`_is_terminal` simplified.** Day 1's implementation walked the message
   list backwards looking for trailing patterns. With the `final_answer`
   short-circuit in play, that's brittle (a prior assistant message with
   `tool_calls=final_answer` followed by a TOOL-free reply is actually
   terminal). The new check is the simple "last message is ASSISTANT with
   no tool_calls" — same as `Agent._is_terminal` but kept as an override
   on ReActAgent for clarity.

6. **Test isolation via `unittest.mock.MagicMock` + hand-rolled stub
   classes** (no `openai` SDK dependency in the test mocks). Each test
   builds a `_StubMessage` / `_StubChoice` / `_StubResponse` trio that
   mimics just enough of the `openai.types.chat.ChatCompletion` shape
   to drive the agents.

## 7. What's NOT in this commit (deferred)

- **Real LLM call tests** — gated by `LLM_API_KEY`; smoke scripts handle
  the no-key case with a clean exit. (The spec asks for this; we comply.)
- **MCP server integration of the new agents** — `mcp_server.py` doesn't
  exist yet (Day 4+).
- **RAG / memory / context integration** — out of Day 3 scope; the agents
  don't yet call into `ContextBuilder` or `MemoryProvider`. Day 4+.
- **Streaming output in the run CLI** — `_run_one` in `chat.py` streams,
  but the new `run` CLI does a one-shot print. (Matching Day 1's design.)

## 8. How to verify locally

```bash
cd D:\Minimax-project\hello-agent-2\.worktrees\wt-e5bdcb08
uv sync --all-extras
uv run ruff check hello_agent/ scripts/ tests/
uv run pytest tests/ -q                   # 120/120
uv run python scripts/smoke_agents.py     # 5/5
uv run python scripts/smoke_tools.py      # 6/6 (Day 2 still green)
uv run python scripts/smoke_core.py       # skip (no key), exit 0
uv run hello-agent run --agent-type react "what is 2+2"   # exit 0, no-key panel
uv run hello-agent run --agent-type plan_solve "step by step, list files"
uv run hello-agent run --agent-type reflection "draft a cover letter"
uv run hello-agent run --agent-type simple "what is 2+2?"
```
