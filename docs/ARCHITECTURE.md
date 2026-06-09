# Architecture (v0.2 minimal)

> Compact ASCII diagram of the v0.2 module map. Full diagrams + sequence
> charts are deferred to v0.3 (when observability ships proper tracing UI).

```
                       ┌────────────────────────────────────────────────────────┐
                       │                   hello_agent (CLI)                    │
                       │            hello-agent chat | run | serve | …          │
                       └─────────────────────────┬──────────────────────────────┘
                                                 │
                                                 ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │                          agents/  (Agent subclasses)                       │
   │   SimpleAgent │ ReActAgent │ PlanAndSolve │ Reflection │ TaskRouter          │
   │                                                                            │
   │   • state machine   • tool dispatch loop   • skills injection (Day 7)        │
   └───────┬────────────────────────────┬──────────────────────────┬────────────┘
           │                            │                          │
           ▼                            ▼                          ▼
   ┌─────────────────┐         ┌──────────────────────┐    ┌──────────────────────┐
   │   core/         │         │   tools/             │    │   memory/            │
   │                 │         │                      │    │                      │
   │ • paths         │         │ • ToolRegistry       │    │ • ShortTermMemory    │
   │ • config        │◀────────│   (auto_discover,    │    │ • LongTermMemory     │
   │ • llm           │         │    circuit breaker,  │    │   (SQLite)           │
   │ • logging       │         │    confirmation)     │    │ • EpisodicMemory     │
   │ • types         │         │ • builtin/ 8 modules │    │ • ObsidianSync       │
   │ • exceptions    │         │   (file / shell /    │    │ • GitSync            │
   └────────┬────────┘         │    web / parse /     │    └──────────┬───────────┘
            │                  │    notify / …)       │               │
            │                  └──────────┬───────────┘               │
            │                             │                           │
            │                             │ MCP routing (Day 6)       │
            │                             ▼                           │
            │                  ┌──────────────────────┐               │
            │                  │   protocols/         │               │
            │                  │   • mcp_client       │               │
            │                  │   • mcp_server       │               │
            │                  │   (stdio JSON-RPC)   │               │
            │                  └──────────────────────┘               │
            │                                                         │
            ▼                                                         ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │                              rag/   (v0.2)                                 │
   │                                                                            │
   │   loader ─▶ chunker ─▶ embedder ─▶ vector_store (chromadb)                  │
   │                                       ▲                                    │
   │                                       │                                    │
   │                              retrieval (4 strategies                       │
   │                               + RRF fusion)                                │
   │                                                                            │
   │   exposed via `hello-agent rag index|query`                                 │
   └────────────────────────────────────────────────────────────────────────────┘

   ┌────────────────────────────────────────────────────────────────────────────┐
   │                          context/ + observability/                         │
   │                                                                            │
   │   history ─ token_counter ─ truncator ─ builder (SessionDB-backed)          │
   │   tracer (per-run tree) + metrics counters                                  │
   └────────────────────────────────────────────────────────────────────────────┘

   ┌────────────────────────────────────────────────────────────────────────────┐
   │                              skills/  (v0.2 Day 7)                         │
   │                                                                            │
   │   SKILL.md loader ─ registry (trigger matching) ─ 3 builtin skills          │
   │   injected into ReActAgent SYSTEM message as <available_skills>             │
   └────────────────────────────────────────────────────────────────────────────┘

   ┌────────────────────────────────────────────────────────────────────────────┐
   │                              web/  (v0.2 Day 8)                            │
   │                                                                            │
   │   FastAPI + SSE + React static UI                                           │
   │   routes: /chat /sessions /skills /tools /config                            │
   └────────────────────────────────────────────────────────────────────────────┘

   ┌────────────────────────────────────────────────────────────────────────────┐
   │                          windows/  (v0.2 Day 9)                            │
   │                                                                            │
   │   tray (pystray) │ autostart (HKCU\…\Run) │ env probe │ hotkeys             │
   └────────────────────────────────────────────────────────────────────────────┘
```

## Layering rules

1. **`core/` is leaf-only.** Nothing in `core/` may import from
   `agents/`, `tools/`, `memory/`, `rag/`, `web/`, `windows/`,
   `skills/`, `protocols/`, or `observability/`.
2. **`protocols/` is independent of `web/`** — the MCP server is a
   pure-Python stdio JSON-RPC server with no FastAPI/SSE dependency.
3. **`windows/` is OS-gated.** Every module that touches `winreg` /
   `pystray` / `pywin32` lazy-imports those packages and raises a
   `HelloAgentError` subclass on non-Windows platforms.
4. **`web/` owns its static assets** under `hello_agent/web/static/`;
   the wheel build force-includes that directory
   (`pyproject.toml` → `[tool.hatch.build.targets.wheel.force-include]`).

## Data flow at a glance

- A user prompt hits `agents.simple.SimpleAgent.run()` →
  `agents.simple.SimpleAgent.step()` → `core.llm.LLMClient.chat()`
  → `openai.OpenAI(...).chat.completions.create()`.
- For `ReActAgent`: same path, but with a tool loop in
  `agents.react.ReActAgent.step()` that dispatches
  `core.types.ToolCall`s through `tools.registry.ToolRegistry.execute()`,
  which honours the **permission** + **circuit breaker** + **MCP routing**
  gates.
- Memory + RAG live behind a context-builder layer (`context.builder`)
  that runs before each LLM call. v0.2 wires the builder into `ReActAgent`
  via the SYSTEM message, so top-K memories + RAG chunks are injected
  in-place.
- The Web UI (Day 8) and the Windows tray (Day 9) are **front-ends**;
  they share the same `agents/` and `tools/` code that the CLI uses.

## Where to read next

- `docs/ENGINEERING.md` §6 — per-module spec
- `docs/TOOL_AUTHORING.md` — extending the registry with custom tools
- `docs/CHANGELOG.md` — what changed in each release