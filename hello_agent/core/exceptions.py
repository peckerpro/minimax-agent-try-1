"""Exception hierarchy for hello-agent."""
from __future__ import annotations


class HelloAgentError(Exception):
    """Base for all hello-agent errors."""


class ConfigError(HelloAgentError):
    """Configuration is missing or invalid."""


class LLMError(HelloAgentError):
    """Generic LLM provider error."""


class LLMTimeoutError(LLMError):
    """LLM request timed out."""


class LLMAuthError(LLMError):
    """LLM provider rejected the API key."""


class LLMRateLimitError(LLMError):
    """LLM provider returned 429."""


class ToolError(HelloAgentError):
    """Generic tool failure."""

    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(f"{tool_name}: {message}")


class ToolNotFoundError(ToolError):
    """Tool name not in registry."""


class ToolPermissionDeniedError(ToolError):
    """Dangerous tool was blocked by permission system."""


class CircuitOpenError(ToolError):
    """Tool's circuit breaker is open (too many recent failures)."""


class MemoryError(HelloAgentError):
    """Memory subsystem failure."""


class RetrievalError(HelloAgentError):
    """RAG subsystem failure."""


class ObsidianSyncError(MemoryError):
    """Obsidian vault sync failure."""


class ContextLengthExceededError(LLMError):
    """LLM call would exceed the context window."""


class AgentInterruptedError(HelloAgentError):
    """User interrupted the agent loop."""
