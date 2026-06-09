"""Tests for hello_agent.cli.main — `--version` exit code."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_hello_agent_version_exits_zero(worktree_root: Path) -> None:
    """`hello-agent --version` must exit 0 and print the version string."""
    env = os.environ.copy()
    # Keep the test sandboxed to the worktree's own venv.
    env.setdefault("HELLO_AGENT_PROFILE", "test")
    env.setdefault("HELLO_AGENT_HOME", str(worktree_root / ".harness" / "test_home"))

    result = subprocess.run(
        ["uv", "run", "hello-agent", "--version"],
        cwd=str(worktree_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, (
        f"hello-agent --version failed:\n"
        f"  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
    )
    # Strip non-printable characters (rich adds them around the text).
    cleaned = "".join(ch for ch in result.stdout if ch.isprintable() or ch in "\n\r")
    assert "hello-agent" in cleaned
    assert "0.2.0" in cleaned
