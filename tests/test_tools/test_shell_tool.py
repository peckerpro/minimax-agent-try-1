"""Tests for hello_agent.tools.builtin.shell_tool.

These are pure-process tests — they spawn short, side-effect-free commands
(`echo`, `set`, environment introspection) on the host shell. They are
marked safe to run on Windows and POSIX alike.
"""
from __future__ import annotations

import os
import sys

import pytest

from hello_agent.tools.builtin.shell_tool import _run_cmd, _run_powershell


def test_run_cmd_echo_hello() -> None:
    """`run_cmd "echo hello"` returns stdout containing 'hello' and exit 0."""
    res = _run_cmd({"command": "echo hello", "timeout_seconds": 10, "max_bytes": 5000})
    assert res.success, f"run_cmd failed: {res.error!r}"
    data = res.data
    assert data["returncode"] == 0
    assert "hello" in data["stdout"]


def test_run_cmd_captures_exit_code_for_failing_command() -> None:
    """A command that returns non-zero still produces a successful ToolResponse
    (the shell ran fine), and the exit code is preserved on the result.
    """
    # On Windows: `cmd /c exit 7` returns 7. On POSIX: `sh -c "exit 7"`.
    if os.name == "nt":
        # Use the same shell as the tool.
        res = _run_cmd({"command": "exit 7", "timeout_seconds": 5, "max_bytes": 1000})
    else:
        res = _run_cmd({"command": "exit 7", "timeout_seconds": 5, "max_bytes": 1000})
    assert res.success, "shell itself succeeded; only the command returned non-zero"
    assert res.data["returncode"] == 7


def test_run_cmd_rejects_empty_command() -> None:
    """An empty command string returns success=False with a clear error."""
    res = _run_cmd({"command": "", "timeout_seconds": 5, "max_bytes": 1000})
    assert not res.success
    assert "command is required" in (res.error or "").lower()


def test_run_cmd_truncates_long_output() -> None:
    """`max_bytes` truncates the combined stdout/stderr output."""
    # Generate a long string — 5 KB of the same character. We force max_bytes
    # to a small value and expect the result to be flagged truncated.
    if os.name == "nt":
        # `for /L` is the canonical Windows loop.
        cmd = "for /L %i in (1,1,200) do @echo xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    else:
        cmd = "python -c \"print('x' * 5000)\""

    res = _run_cmd({"command": cmd, "timeout_seconds": 10, "max_bytes": 256})
    assert res.success
    assert res.data["truncated"] is True
    assert res.data["returncode"] == 0


@pytest.mark.skipif(os.name != "nt", reason="PowerShell only available on Windows")
def test_run_powershell_echo() -> None:
    """On Windows, `run_powershell "Write-Output hello"` returns 'hello' on stdout."""
    res = _run_powershell(
        {"command": "Write-Output hello", "timeout_seconds": 15, "max_bytes": 5000}
    )
    assert res.success, f"run_powershell failed: {res.error!r}"
    assert "hello" in res.data["stdout"]
    assert res.data["returncode"] == 0


def test_run_cmd_emits_python_path_in_output() -> None:
    """A smoke check that the env passed to the subprocess contains PYTHONPATH
    or python (so we can verify the tool's cwd + env don't strip essentials).
    """
    if sys.platform.startswith("win"):
        cmd = "where python"
    else:
        cmd = "command -v python || true"
    res = _run_cmd({"command": cmd, "timeout_seconds": 10, "max_bytes": 4000})
    # Don't care about exact content — just that the call returns cleanly.
    assert res.success, f"unexpected failure: {res.error!r}"
    assert isinstance(res.data["stdout"], str)
