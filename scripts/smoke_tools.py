"""Smoke test for the hello_agent.tools layer.

Exercises the public surface of §6.4 + §7.1 end-to-end without spinning up
the LLM, the agent loop, or a real LLM API key:

  1. `ToolRegistry.register` / `get` / `list` round-trip — own fresh registry,
     so this test does not depend on the shared singleton's state.
  2. `ToolResponse` shape (success=True path) — constructed via `ok()`,
     read back via `to_json()`.
  3. `CircuitBreaker` state transitions — drive a mocked failure counter
     through the closed → open → half-open → closed cycle.
  4. `document_parser` fallback chain — feed it a tiny inline markdown
     string written to a temp .md file. The `is_text` chain is just the
     raw UTF-8 reader, so it succeeds without MinerU / markitdown / pypdf.
     The error path is also checked: pointing at a non-existent PDF and
     confirming the `All parsers failed` hint is populated.
  5. `file_tools.read_file` / `write_file` round-trip on a temp file.
  6. `shell_tool.run_cmd "echo hello"` — assert stdout contains "hello".

Run from the worktree root:
    uv run python scripts/smoke_tools.py

Exit codes:
  0   every section passed
  1   a section reported a hard failure
  2   an unexpected exception escaped
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

# --- section helpers --------------------------------------------------------


class SmokeError(AssertionError):
    """A section reported a hard failure."""


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _ok(msg: str) -> None:
    print(f"  [ok] {msg}")


def _info(msg: str) -> None:
    print(f"  [..] {msg}")


# --- section 1: ToolRegistry round-trip -------------------------------------


def smoke_registry() -> None:
    _section("1. ToolRegistry register/get/list round-trip")
    from hello_agent.core.types import ToolDefinition, ToolResult
    from hello_agent.tools.registry import ToolRegistry

    reg = ToolRegistry()
    assert len(reg.list()) == 0, "fresh registry should be empty"

    schema = ToolDefinition(
        name="smoke_echo",
        description="echoes the input back as a string",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    def handler(args: dict, **kw: object) -> ToolResult:
        return ToolResult(tool_call_id=str(kw.get("tool_call_id", "")), content=str(args.get("text", "")))

    reg.register(
        name="smoke_echo",
        toolset="smoke",
        schema=schema,
        handler=handler,
    )
    _ok("register('smoke_echo') succeeded")

    assert "smoke_echo" in [t.name for t in reg.list()], "list() should include smoke_echo"
    _ok("list() contains 'smoke_echo'")

    fetched = reg.get("smoke_echo")
    assert fetched.name == "smoke_echo"
    assert fetched.toolset == "smoke"
    _ok("get('smoke_echo') returned the registered entry")

    result = reg.execute("smoke_echo", {"text": "hello registry"})
    assert result.content == "hello registry", f"unexpected content: {result.content!r}"
    assert not result.is_error
    _ok("execute(...) returned the echoed string")

    # filter_by_profile
    by_profile = reg.filter_by_profile("smoke")
    assert len(by_profile) == 1 and by_profile[0].name == "smoke_echo"
    _ok("filter_by_profile('smoke') returned the smoke_echo entry")

    # unregister
    assert reg.unregister("smoke_echo") is True
    assert reg.unregister("smoke_echo") is False  # idempotent
    assert reg.list() == []
    _ok("unregister() removed the entry (idempotent)")

    from hello_agent.core.exceptions import ToolNotFoundError
    try:
        reg.get("smoke_echo")
    except ToolNotFoundError:
        _ok("get() on a removed entry raises ToolNotFoundError")
    else:
        raise SmokeError("get() should have raised ToolNotFoundError after unregister")


# --- section 2: ToolResponse shape ------------------------------------------


def smoke_response_shape() -> None:
    _section("2. ToolResponse shape (success=True)")
    from hello_agent.tools.response import ToolResponse

    r = ToolResponse.ok({"text": "world", "size": 5})
    assert r.success is True
    assert r.data == {"text": "world", "size": 5}
    assert r.error is None
    assert r.hint is None
    _ok("ToolResponse.ok({'text': 'world', 'size': 5}) round-trips data")

    blob = r.to_json()
    assert isinstance(blob, str)
    assert '"success": true' in blob
    assert '"text": "world"' in blob
    _ok(f"to_json() -> {blob!r}")

    # Also verify the failure constructor
    r2 = ToolResponse.fail("boom", hint="try again")
    assert r2.success is False
    assert r2.error == "boom"
    assert r2.hint == "try again"
    _ok("ToolResponse.fail(error, hint) populates error+hint")


# --- section 3: CircuitBreaker state transitions ---------------------------


def smoke_circuit_breaker() -> None:
    _section("3. CircuitBreaker state transitions")
    from hello_agent.tools.circuit_breaker import CircuitBreaker

    # Use a fresh breaker with tight thresholds so the test is fast.
    cb = CircuitBreaker(fail_threshold=2, window_seconds=10.0, cooldown_seconds=0.05)

    # closed → allow
    assert cb.state("demo") == CircuitBreaker.STATE_CLOSED
    assert cb.allow("demo") is True
    _ok("initial state=closed, allow()=True")

    # closed → open after N failures
    cb.record_failure("demo")
    assert cb.state("demo") == CircuitBreaker.STATE_CLOSED
    cb.record_failure("demo")
    assert cb.state("demo") == CircuitBreaker.STATE_OPEN
    assert cb.allow("demo") is False
    _ok("after fail_threshold=2 failures, state=open, allow()=False")

    # open → half-open after cooldown
    import time

    time.sleep(0.06)  # > cooldown_seconds
    assert cb.allow("demo") is True
    assert cb.state("demo") == CircuitBreaker.STATE_HALF_OPEN
    _ok("after cooldown elapses, state=half_open and the next call is allowed")

    # half-open → closed on success
    cb.record_success("demo")
    assert cb.state("demo") == CircuitBreaker.STATE_CLOSED
    assert cb.allow("demo") is True
    _ok("record_success in half_open transitions back to closed")

    # And a failure in half-open re-opens
    cb.record_failure("demo")
    cb.record_failure("demo")
    assert cb.state("demo") == CircuitBreaker.STATE_OPEN
    time.sleep(0.06)
    cb.allow("demo")  # → half_open
    assert cb.state("demo") == CircuitBreaker.STATE_HALF_OPEN
    cb.record_failure("demo")
    assert cb.state("demo") == CircuitBreaker.STATE_OPEN
    _ok("record_failure in half_open re-opens the circuit")

    # Aliases for the day-2 spec names
    cb2 = CircuitBreaker(failure_threshold=3, reset_timeout_ms=100)
    assert cb2.fail_threshold == 3
    assert cb2.cooldown_seconds == 0.1
    _ok(
        "day-2 alias kwargs work: CircuitBreaker(failure_threshold=3, reset_timeout_ms=100) "
        "→ fail_threshold=3, cooldown_seconds=0.1"
    )


# --- section 4: document_parser fallback chain -----------------------------


def smoke_document_parser(tmp_dir: Path) -> None:
    _section("4. document_parser fallback chain")
    from hello_agent.tools.builtin.document_parser import parse_document

    # 4a. Inline markdown → raw chain → success
    md_path = tmp_dir / "smoke_inline.md"
    md_path.write_text("# hello\n\nThis is a tiny inline markdown body.\n", encoding="utf-8")
    resp = parse_document(str(md_path))
    assert resp.success, f"expected success, got error={resp.error!r}"
    assert resp.data is not None
    assert "parser_used" in resp.data
    assert resp.data["parser_used"] == "raw", f"expected raw, got {resp.data['parser_used']!r}"
    assert "hello" in resp.data["text"]
    _ok(f"parse_document on .md → success via {resp.data['parser_used']}")

    # 4b. Non-existent path → failure with hint
    resp_fail = parse_document(str(tmp_dir / "does_not_exist.pdf"))
    assert not resp_fail.success
    assert resp_fail.error is not None
    _ok(f"parse_document on missing path → fail: {resp_fail.error!r}")

    # 4c. PDF path with no MinerU/markitdown/pypdf: chain still attempts in order,
    # and (since they're optional deps we may not have) either succeeds via pypdf
    # or fails with a 'All parsers failed' hint. Either way, no exception escapes.
    pdf_path = tmp_dir / "fake.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%fake content for smoke test\n")
    try:
        resp_pdf = parse_document(str(pdf_path))
    except Exception as exc:  # noqa: BLE001
        raise SmokeError(f"parse_document raised on a PDF (should never raise): {exc}") from exc
    if resp_pdf.success:
        _ok(
            f"parse_document on .pdf → success via {resp_pdf.data.get('parser_used')!r} "
            f"(markitdown/pypdf are installed)"
        )
    else:
        assert "All parsers failed" in (resp_pdf.error or "")
        _ok("parse_document on .pdf → fail with 'All parsers failed' (no parsers installed)")

    # 4d. force_parser=raw short-circuits
    resp_raw = parse_document(str(md_path), force_parser="raw")
    assert resp_raw.success and resp_raw.data["parser_used"] == "raw"
    _ok("force_parser='raw' short-circuits the chain")


# --- section 5: file_tools read/write round-trip ---------------------------


def smoke_file_tools(tmp_dir: Path) -> None:
    _section("5. file_tools read/write round-trip")
    from hello_agent.tools.builtin.file_tools import (
        _edit_file,
        _read_file,
        _write_file,
    )

    target = tmp_dir / "smoke_round_trip.txt"
    payload = "first line\nsecond line\nthird line\n"
    res = _write_file({"path": str(target), "content": payload})
    assert res.success, f"write_file failed: {res.error!r}"
    assert target.exists()
    _ok("write_file wrote the payload")

    res = _read_file({"path": str(target)})
    assert res.success, f"read_file failed: {res.error!r}"
    assert res.data["text"] == payload
    _ok(f"read_file read back {res.data['size_bytes']} bytes")

    res = _edit_file(
        {
            "path": str(target),
            "old": "second line",
            "new": "SECOND LINE (edited)",
        }
    )
    assert res.success, f"edit_file failed: {res.error!r}"
    _ok("edit_file replaced 'second line' → 'SECOND LINE (edited)'")

    res = _read_file({"path": str(target)})
    assert res.success
    assert "SECOND LINE (edited)" in res.data["text"]
    assert "second line" not in res.data["text"]
    _ok("read_file confirms the edit landed on disk")

    # And an edit_file with an ambiguous `old` is rejected.
    (tmp_dir / "ambig.txt").write_text("aaa\naaa\n", encoding="utf-8")
    res = _edit_file(
        {
            "path": str(tmp_dir / "ambig.txt"),
            "old": "aaa",
            "new": "bbb",
        }
    )
    assert not res.success
    assert "disambiguate" in (res.error or "").lower()
    _ok("edit_file with ambiguous 'old' (matches 2 places) is rejected")


# --- section 6: shell_tool echo ---------------------------------------------


def smoke_shell_tool() -> None:
    _section("6. shell_tool.run_cmd 'echo hello'")
    from hello_agent.tools.builtin.shell_tool import _run_cmd

    res = _run_cmd({"command": "echo hello", "timeout_seconds": 10, "max_bytes": 5000})
    assert res.success, f"run_cmd failed: {res.error!r}"
    stdout = res.data["stdout"] if isinstance(res.data, dict) else str(res.data)
    assert "hello" in stdout, f"expected 'hello' in stdout, got {stdout!r}"
    _ok(f"stdout contains 'hello': {stdout.strip()!r}")
    assert res.data.get("returncode", 1) == 0
    _ok("returncode == 0")


# --- driver -----------------------------------------------------------------


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="smoke_tools_") as td:
        tmp_dir = Path(td)
        _info(f"tmp dir = {tmp_dir}")

        sections: list[tuple[str, callable]] = [
            ("smoke_registry", smoke_registry),
            ("smoke_response_shape", smoke_response_shape),
            ("smoke_circuit_breaker", smoke_circuit_breaker),
            ("smoke_document_parser", lambda: smoke_document_parser(tmp_dir)),
            ("smoke_file_tools", lambda: smoke_file_tools(tmp_dir)),
            ("smoke_shell_tool", smoke_shell_tool),
        ]

        for name, fn in sections:
            try:
                fn()
            except SmokeError as exc:
                print(f"  [FAIL] {name}: {exc}", file=sys.stderr)
                failures.append(name)
            except Exception as exc:  # noqa: BLE001
                print(f"  [CRASH] {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                traceback.print_exc()
                failures.append(name)

    if failures:
        print(f"\n[smoke_tools] FAIL: {len(failures)} section(s) failed: {failures}", file=sys.stderr)
        return 1
    print("\n[smoke_tools] OK: all 6 sections passed")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--workdir" and len(sys.argv) > 2:
        os.chdir(sys.argv[2])
    sys.exit(main())
