"""shell_tool — run_powershell, run_cmd.

On Windows, default to PowerShell. On other platforms, fall back to a shell
that handles `command` as a single string. Marked dangerous.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any

from hello_agent.core.config import get_config
from hello_agent.core.types import ToolDefinition, ToolResponse, ToolResult
from hello_agent.tools.registry import ToolRegistry


def _truncate(text: str, max_bytes: int) -> tuple[str, bool]:
    data = text.encode("utf-8", errors="replace")
    if len(data) <= max_bytes:
        return text, False
    return data[:max_bytes].decode("utf-8", errors="replace"), True


def _run_subprocess(command: str, timeout: int, max_bytes: int, shell_args: list[str]) -> ToolResponse:
    try:
        result = subprocess.run(
            shell_args + [command] if shell_args else command,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            shell=bool(shell_args) is False,
        )
    except subprocess.TimeoutExpired:
        return ToolResponse.fail(f"Command timed out after {timeout}s")
    except FileNotFoundError as exc:
        return ToolResponse.fail(f"Shell not found: {exc}")
    except OSError as exc:
        return ToolResponse.fail(f"OS error: {exc}")

    out = (result.stdout or "") + (result.stderr or "")
    truncated_text, was_truncated = _truncate(out, max_bytes)
    return ToolResponse.ok(
        {
            "stdout": truncated_text,
            "returncode": result.returncode,
            "truncated": was_truncated,
        }
    )


def _run_powershell(args: dict[str, Any]) -> ToolResponse:
    cmd = args.get("command", "")
    if not cmd:
        return ToolResponse.fail("command is required")
    timeout = int(args.get("timeout_seconds", get_config().terminal.shell_timeout_seconds))
    max_bytes = int(args.get("max_bytes", get_config().terminal.shell_max_output_bytes))
    return _run_subprocess(cmd, timeout, max_bytes, ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"])


def _run_cmd(args: dict[str, Any]) -> ToolResponse:
    cmd = args.get("command", "")
    if not cmd:
        return ToolResponse.fail("command is required")
    timeout = int(args.get("timeout_seconds", get_config().terminal.shell_timeout_seconds))
    max_bytes = int(args.get("max_bytes", get_config().terminal.shell_max_output_bytes))
    if os.name == "nt":
        return _run_subprocess(cmd, timeout, max_bytes, ["cmd.exe", "/c"])
    return _run_subprocess(cmd, timeout, max_bytes, ["/bin/sh", "-c"])


def _to_result(response: ToolResponse, tool_call_id: str) -> ToolResult:
    content = (
        response.data
        if isinstance(response.data, str)
        else (response.to_json() if response.data is not None else "")
    )
    return ToolResult(tool_call_id=tool_call_id, content=content, is_error=not response.success)


def register(registry: ToolRegistry) -> None:
    registry.register(
        name="run_powershell",
        toolset="shell_tool",
        schema=ToolDefinition(
            name="run_powershell",
            description="Run a PowerShell command (Windows) and return combined stdout/stderr.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The PowerShell command."},
                    "timeout_seconds": {"type": "integer"},
                    "max_bytes": {"type": "integer"},
                },
                "required": ["command"],
            },
            requires_confirmation=True,
        ),
        handler=lambda args, **kw: _to_result(_run_powershell(args), kw.get("tool_call_id", "")),
        dangerous=True,
    )
    registry.register(
        name="run_cmd",
        toolset="shell_tool",
        schema=ToolDefinition(
            name="run_cmd",
            description="Run a cmd.exe (Windows) or /bin/sh (POSIX) command and return its output.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "max_bytes": {"type": "integer"},
                },
                "required": ["command"],
            },
            requires_confirmation=True,
        ),
        handler=lambda args, **kw: _to_result(_run_cmd(args), kw.get("tool_call_id", "")),
        dangerous=True,
    )
