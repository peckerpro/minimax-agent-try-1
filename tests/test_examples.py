"""Verify every example script in `examples/` runs cleanly with `--self-test`.

Each `examples/NN_*.py` ships with an offline smoke flag (`--self-test`)
that exercises the relevant public API without LLM calls / network. The
verifier subprocesses them one at a time and asserts exit 0.

The tests use `uv run python` so the example scripts share the project's
resolved venv (matching the lockfile). They run in the worktree root so
the relative paths inside the examples resolve correctly.

The MCP example (05) is the only one that spawns a real subprocess
(`python -m hello_agent.cli.mcp serve`). It still needs no API keys;
it just exercises the JSON-RPC stdio wire format against itself.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _example_paths() -> list[Path]:
    """Return the sorted list of `examples/NN_*.py` files."""
    return sorted(p for p in EXAMPLES_DIR.glob("[0-9][0-9]_*.py"))


@pytest.mark.parametrize(
    "example",
    _example_paths(),
    ids=lambda p: p.stem,
)
def test_example_self_test_exits_zero(example: Path, worktree_root: Path) -> None:
    """Each `examples/NN_*.py --self-test` must exit 0 within 60s."""
    env = os.environ.copy()
    # Keep the test sandboxed — same approach the cli/test_version.py uses.
    env.setdefault("HELLO_AGENT_PROFILE", "test")
    env.setdefault("HELLO_AGENT_HOME", str(worktree_root / ".harness" / "test_home"))

    start = time.time()
    result = subprocess.run(
        ["uv", "run", "python", str(example), "--self-test"],
        cwd=str(worktree_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    elapsed = time.time() - start

    assert result.returncode == 0, (
        f"{example.name} --self-test failed "
        f"(exit={result.returncode}, elapsed={elapsed:.2f}s):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}\n"
    )
    # Sanity: every self-test prints an "[self-test] OK" line. The MCP
    # example uses "[self-test] OK" too. Other examples should follow.
    assert "[self-test] OK" in result.stdout, (
        f"{example.name} did not print the expected [self-test] OK marker:\n"
        f"--- stdout ---\n{result.stdout}"
    )


def test_examples_directory_has_five_runnable_scripts() -> None:
    """Guard rail: release must ship exactly 5 example scripts."""
    paths = _example_paths()
    assert len(paths) == 5, (
        f"expected 5 example scripts (01-05), found {len(paths)}: {[p.name for p in paths]}"
    )
    # Each must declare a --self-test flag.
    for p in paths:
        text = p.read_text(encoding="utf-8")
        assert "--self-test" in text, f"{p.name} missing --self-test flag"