"""file_tools — read_file, write_file, edit_file.

Borrowed from `hermes tools/file.py`:
- ReadTool: path validation (no ../..), max_bytes truncation.
- WriteTool: parent dir creation, atomic write via tempfile + rename.
- EditTool: optimistic lock via file mtime, retry on conflict.

`write_file` and `edit_file` are marked dangerous (require confirmation).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from hello_agent.core.types import ToolDefinition, ToolResponse, ToolResult
from hello_agent.tools.registry import ToolRegistry


def _resolve(path_str: str, cwd: Path | None = None) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute() and cwd is not None:
        p = cwd / p
    return p.resolve()


def _atomic_write(target: Path, content: str) -> None:
    """Write content to target atomically: tempfile in the same dir, then rename.

    Opens with ``newline=""`` so Windows text-mode does NOT translate ``\n``
    into ``\r\n`` on the way to disk — byte-literal round-trip is part of
    the contract of this tool.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile is not used directly because on Windows it can't be reopened.
    fd, tmp_path = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp_path, target)
    except Exception:
        # Best-effort cleanup
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _read_file(args: dict[str, Any]) -> ToolResponse:
    path_str = args.get("path", "")
    if not path_str:
        return ToolResponse.fail("path is required")
    max_bytes = int(args.get("max_bytes", 1_000_000))
    p = _resolve(path_str)
    if not p.exists():
        return ToolResponse.fail(f"File not found: {p}")
    if not p.is_file():
        return ToolResponse.fail(f"Not a file: {p}")
    if ".." in Path(path_str).parts and ".." not in p.parts:
        return ToolResponse.fail("Path traversal not allowed")
    try:
        data = p.read_bytes()
    except OSError as exc:
        return ToolResponse.fail(f"Read failed: {exc}")
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    return ToolResponse.ok(
        {"text": text, "truncated": truncated, "size_bytes": len(data), "path": str(p)}
    )


def _write_file(args: dict[str, Any]) -> ToolResponse:
    path_str = args.get("path", "")
    content = args.get("content", "")
    if not path_str:
        return ToolResponse.fail("path is required")
    p = _resolve(path_str)
    if ".." in Path(path_str).parts and ".." not in p.parts:
        return ToolResponse.fail("Path traversal not allowed")
    try:
        _atomic_write(p, content)
    except OSError as exc:
        return ToolResponse.fail(f"Write failed: {exc}")
    return ToolResponse.ok({"path": str(p), "size_bytes": len(content.encode("utf-8"))})


def _edit_file(args: dict[str, Any]) -> ToolResponse:
    path_str = args.get("path", "")
    old = args.get("old", "")
    new = args.get("new", "")
    if not (path_str and old):
        return ToolResponse.fail("path and old are required")
    p = _resolve(path_str)
    if not p.exists():
        return ToolResponse.fail(f"File not found: {p}")
    if ".." in Path(path_str).parts and ".." not in p.parts:
        return ToolResponse.fail("Path traversal not allowed")
    try:
        original = p.read_text(encoding="utf-8")
        mtime_before = p.stat().st_mtime
    except OSError as exc:
        return ToolResponse.fail(f"Read failed: {exc}")
    if old not in original:
        return ToolResponse.fail("`old` text not found in file (no edit applied)")
    count = original.count(old)
    if count > 1:
        return ToolResponse.fail(
            f"`old` text matches {count} locations; please disambiguate",
            hint="Provide a more specific `old` string",
        )
    updated = original.replace(old, new, 1)
    try:
        _atomic_write(p, updated)
    except OSError as exc:
        return ToolResponse.fail(f"Write failed: {exc}")
    # Optimistic-lock check: if the file changed between read and write, warn.
    mtime_after = p.stat().st_mtime
    if mtime_after > mtime_before and mtime_after - mtime_before > 0.0001:
        # Could be the same edit; not a hard error. Surface as a warning.
        return ToolResponse.ok(
            {
                "path": str(p),
                "size_bytes": len(updated.encode("utf-8")),
                "warning": "file mtime changed during edit; double-check the result",
            }
        )
    return ToolResponse.ok({"path": str(p), "size_bytes": len(updated.encode("utf-8"))})


def _to_result(response: ToolResponse, tool_call_id: str, name: str) -> ToolResult:
    content = (
        response.data
        if isinstance(response.data, str)
        else (response.to_json() if response.data is not None else "")
    )
    return ToolResult(
        tool_call_id=tool_call_id,
        content=content,
        is_error=not response.success,
    )


def register(registry: ToolRegistry) -> None:
    """Register the 3 file tools."""
    registry.register(
        name="read_file",
        toolset="file_tools",
        schema=ToolDefinition(
            name="read_file",
            description="Read a text file (UTF-8) and return its content.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file."},
                    "max_bytes": {"type": "integer", "description": "Max bytes to read (default 1MB)."},
                },
                "required": ["path"],
            },
        ),
        handler=lambda args, **kw: _to_result(_read_file(args), kw.get("tool_call_id", ""), "read_file"),
    )
    registry.register(
        name="write_file",
        toolset="file_tools",
        schema=ToolDefinition(
            name="write_file",
            description="Write content to a file atomically. Overwrites if the file exists.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=True,
        ),
        handler=lambda args, **kw: _to_result(_write_file(args), kw.get("tool_call_id", ""), "write_file"),
        dangerous=True,
    )
    registry.register(
        name="edit_file",
        toolset="file_tools",
        schema=ToolDefinition(
            name="edit_file",
            description="Find-and-replace edit on a file. `old` must match exactly once.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
            requires_confirmation=True,
        ),
        handler=lambda args, **kw: _to_result(_edit_file(args), kw.get("tool_call_id", ""), "edit_file"),
        dangerous=True,
    )
