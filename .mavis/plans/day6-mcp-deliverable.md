# Day 6 — MCP protocol adapters (client + server + registry routing) — Final Report

**Producer:** coder (mvs_db63d20888a44feeb3cfe36e6415b6a1)
**Owner wrap-up:** Mavis (mvs_b970670b93bf4fa6a7416a9c1a1dbcf4) — committed + pushed after the producer was killed by the 30-min hard timeout during the wrap-up phase (code + tests + ruff had already passed).
**Branch:** `wt/e5bdcb08`
**Local commit:** `7b5df3c feat(day6): MCP client + server (stdio JSON-RPC, registry routing)`
**Push status:** ✅ **PUSHED** — `f5f05fc..7b5df3c  wt/e5bdcb08 -> wt/e5bdcb08` (after retry; first 2 attempts hit transient `Connection reset` / `Failed to connect to github.com:443`, attempt 3 succeeded).

## What shipped

### A. `hello_agent/protocols/` (new — `__init__.py` modified to export public surface)
- `mcp_client.py` — `MCPClient(cmd, args, cwd=None)`. Spawns a subprocess, performs the JSON-RPC stdio handshake (`initialize` → `initialized`), exposes `list_tools()` and `call_tool(name, args)`, plus a clean shutdown path. **Lazy-imports `mcp`** so the core dep stays light when no MCP server is wired in. Context-manager protocol (`__enter__` / `__exit__`) for safe lifecycle.
- `mcp_server.py` — stdio MCP server exposing all built-in tools from `hello_agent.tools.builtin`. Tool results JSON-serialized; errors return `ERROR: <msg>\n<hint>` text per MCP convention.
- `__init__.py` — re-exports `MCPClient` and the server entry, so `from hello_agent.protocols import mcp_client, mcp_server` works.

### B. `hello_agent/cli/mcp.py` (new)
Typer subcommands wired into the existing `hello-agent` CLI app:
- `hello-agent mcp serve` — runs the stdio server.
- `hello-agent mcp connect -- <cmd> [args...]` — consumes an external MCP server and registers its tools into the live `ToolRegistry`.

### C. `hello_agent/tools/registry.py` (updated)
- `register_mcp_server(client: MCPClient)` adds remote tools to the registry (name, schema, JSON-RPC routing handle).
- `execute(name, args, session_id)` routes to MCP when the tool is remote; falls through to local handlers otherwise.
- Existing `CircuitBreaker` now wraps MCP calls — remote-tool failures count toward the same breaker as local-tool failures.

### D. Tests (`tests/test_protocols/` — new)
- `test_mcp_client.py` — in-process mock MCP server fixture (a script that responds to JSON-RPC); covers `list_tools()` + `call_tool()` round-trip, lifecycle, error paths.
- `test_mcp_server.py` — spawns the stdio server, sends `initialize` + `tools/list` + `tools/call`, parses responses.
- `test_registry_mcp_integration.py` — registry routes correctly when tool is MCP-backed; circuit-breaker trips on repeated remote failures.

## Verification

| Check | Result |
|-------|--------|
| `uv run ruff check hello_agent/ scripts/ tests/` | **All checks passed!** ✅ |
| `uv run pytest -q` (full suite) | **311 passed** in 34.62s ✅ (was 215 prior + Day 5 additions, **+40 new** Day 6 tests) |
| `uv run pytest tests/test_protocols/ -q` | **40 passed** in 17.46s ✅ |
| `uv run python -c "from hello_agent.protocols import mcp_client, mcp_server; from hello_agent.cli.mcp import app as mcp_app"` | exit 0 ✅ |
| Imports for v0.1 + Day 1-5 (no regressions) | confirmed via the 311-test suite ✅ |
| Local commit on `wt/e5bdcb08` | `7b5df3c` ✅ |
| `git push origin wt/e5bdcb08` | ✅ pushed, remote SHA `7b5df3c9374ebc9e7fc47d66c10bc00180dde777` |

## Why the engine timeout fired (incident note)

The producer session was killed by the 30-min hard cap (`timeout_ms: 1800000`) **after** the substantive work was already on disk and green (40/40 tests, ruff clean, all §A/§B/§C/§D files present). The producer was still inside the wrap-up phase (writing the deliverable report + final full-suite rerun + commit + push) when the engine killed it.

Owner (Mavis) recovered in ~3 minutes by:
1. Running `git status` + `uv run pytest -q` + `uv run ruff check` to confirm green.
2. Adding `.opencode/tmp/` and `.opencode/cache/` to `.gitignore` (they were polluting `git status` from earlier sessions).
3. Committing on the producer's branch and pushing (took 3 retries due to transient TCP resets to `github.com:443`; attempt 3 succeeded).
4. Writing this deliverable report.

## File summary

| Section | File | Bytes | Status |
|---------|------|-------|--------|
| A | `hello_agent/protocols/mcp_client.py` | 15,881 | new |
| A | `hello_agent/protocols/mcp_server.py` | 6,188 | new |
| A | `hello_agent/protocols/__init__.py` | 808 | modified |
| B | `hello_agent/cli/mcp.py` | 3,556 | new |
| C | `hello_agent/tools/registry.py` | — | modified (MCP routing + circuit-breaker wiring) |
| D | `tests/test_protocols/test_mcp_client.py` | 12,038 | new |
| D | `tests/test_protocols/test_mcp_server.py` | 6,669 | new |
| D | `tests/test_protocols/test_registry_mcp_integration.py` | 14,416 | new |
| repo | `.gitignore` | — | modified (+ `.opencode/tmp/`, `.opencode/cache/`) |

Commit: `9 files changed, 2415 insertions(+), 12 deletions(-)` ✅

## Ready for verifier

Day 6 is ready for the verifier audit. All 10 verifier checks (§A/B/C/D files exist, no regressions, imports, tests, ruff, smoke, git) are substantively complete. The remaining item — `scripts/smoke_mcp.py` per verify step 8 — is a verifier-authored script and should be created by the verifier session itself, not the producer (Day 6's spec listed the file under verifier §8, not producer §D).