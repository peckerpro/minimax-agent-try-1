"""Core data types: messages, tool definitions, agent state, tool responses."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """Chat message role."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """An LLM's request to invoke a tool."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The result of a tool invocation, fed back to the LLM as a tool message."""

    tool_call_id: str
    content: str  # stringified JSON (LLMs prefer text)
    is_error: bool = False
    truncated: bool = False
    full_output_path: str | None = None  # if output was saved to a file


@dataclass
class Message:
    """A single chat message in the conversation history.

    role:            one of SYSTEM/USER/ASSISTANT/TOOL
    content:         text content (None for assistant messages that are pure tool_calls)
    tool_calls:      set only on assistant messages that want tools to run
    tool_call_id:    set only on tool messages (echoes the assistant's tool_call.id)
    tool_name:       set only on tool messages (for human-readable logs)
    """

    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    name: str | None = None
    timestamp: float = field(default_factory=lambda: time.time())
    token_count: int | None = None
    finish_reason: str | None = None
    reasoning: str | None = None
    cache_breakpoint: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serializable dict (used for SQLite persistence)."""
        d = asdict(self)
        d["role"] = self.role.value
        if self.tool_calls is not None:
            d["tool_calls"] = [asdict(tc) for tc in self.tool_calls]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Message:
        """Inverse of to_dict."""
        data = dict(d)
        data["role"] = Role(data.pop("role"))
        tcs = data.get("tool_calls")
        if tcs is not None:
            data["tool_calls"] = [ToolCall(**tc) for tc in tcs]
        return cls(**data)


@dataclass
class ToolDefinition:
    """JSON-schema description of a tool, sent to the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (object type)
    requires_confirmation: bool = False


@dataclass
class ToolResponse:
    """Result envelope for a tool execution.

    success: True if the tool ran successfully (data may still contain warnings)
    data:    the actual result — type depends on the tool
    error:   human-readable error message when success=False
    hint:    optional next-step suggestion (e.g. "Try a different file path")
    """

    success: bool
    data: Any = None
    error: str | None = None
    hint: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "success": self.success,
                "data": self.data,
                "error": self.error,
                "hint": self.hint,
            },
            ensure_ascii=False,
            default=str,
        )

    @classmethod
    def ok(cls, data: Any) -> ToolResponse:
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str, hint: str | None = None) -> ToolResponse:
        return cls(success=False, error=error, hint=hint)

    @classmethod
    def from_exception(cls, exc: Exception) -> ToolResponse:
        return cls(success=False, error=f"{type(exc).__name__}: {exc}")


@dataclass
class AgentState:
    """Mutable state carried through one agent loop."""

    session_id: str
    messages: list[Message]
    iteration: int = 0
    max_iterations: int = 30
    interrupted: bool = False
    spent_usd: float = 0.0
    max_cost_per_turn_usd: float = 0.50
    trace_id: str | None = None
