"""Tests for `hello-agent memory show` CLI subcommand.

Regression coverage for the v0.2 ship-bug where `memory show` called
`mem.list_recent(limit=...)`, which does not exist on `LongTermMemory`.
The fix replaced it with `list_facts()` (ordered by id ASC) reversed and
sliced, and added a friendly empty-state message.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path


def _run_memory_show(worktree_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke `uv run hello-agent memory show ...` with a sandboxed $HELLO_AGENT_HOME.

    Each test gets its own fresh, empty $HELLO_AGENT_HOME so the empty-state
    case is exercised deterministically (the default home in the worktree
    has at least one fact from earlier ad-hoc invocations).
    """
    sandbox = Path(os.environ["TEMP"]) / f"ha_test_{uuid.uuid4().hex}"
    sandbox.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HELLO_AGENT_PROFILE"] = "test"
    env["HELLO_AGENT_HOME"] = str(sandbox)
    env["HELLO_AGENT_DOTENV_PATH"] = str(sandbox / ".env")
    env.pop("HELLO_AGENT_SETUP_LOGGING", None)

    cmd = ["uv", "run", "hello-agent", "memory", "show", *args]
    return subprocess.run(
        cmd,
        cwd=str(worktree_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_memory_show_empty_state_prints_friendly_message(worktree_root: Path) -> None:
    """With a fresh empty home, `memory show` must exit 0 and print the empty-state hint."""
    result = _run_memory_show(worktree_root)

    assert result.returncode == 0, (
        f"hello-agent memory show failed (empty home):\n"
        f"  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
    )
    out = result.stdout
    assert "(no memories yet" in out, f"expected empty-state hint in stdout, got: {out!r}"
    # Friendly: should point the user at the next action.
    assert "export" in out


def test_memory_show_json_empty_returns_empty_list(worktree_root: Path) -> None:
    """With a fresh empty home, `memory show --json` must print `[]` and exit 0."""
    result = _run_memory_show(worktree_root, "--json")

    assert result.returncode == 0, (
        f"hello-agent memory show --json failed (empty home):\n"
        f"  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
    )
    # The CLI pretty-prints with indent=2, so the output is "[]" on a line.
    parsed = json.loads(result.stdout)
    assert parsed == [], f"expected empty list, got: {parsed!r}"


def test_memory_show_exit_code_is_zero(worktree_root: Path) -> None:
    """Explicit exit-code assertion: the ship-bug surfaced as a Python traceback + exit 1.

    Even on the empty-state path, we must not regress to a non-zero exit.
    """
    result = _run_memory_show(worktree_root)
    assert result.returncode == 0
    # And the stderr must not contain a Python traceback.
    assert "Traceback" not in result.stderr
    assert "AttributeError" not in result.stderr
