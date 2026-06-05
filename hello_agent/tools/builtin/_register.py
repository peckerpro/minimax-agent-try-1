"""Register all builtin tools with a target ToolRegistry.

Idempotent — safe to call multiple times on the same registry.

Usage:
    from hello_agent.tools.builtin._register import register_all
    register_all()                    # registers into the shared singleton
    register_all(my_registry)         # registers into an explicit registry
"""
from __future__ import annotations

from hello_agent.tools.builtin import (
    document_parser,
    file_tools,
    notify,
    shell_tool,
    task_tool,
    todowrite,
    web_fetch,
    web_search,
)
from hello_agent.tools.registry import ToolRegistry, registry


def register_all(target: ToolRegistry | None = None) -> None:
    """Register all builtin tools into `target` (or the shared singleton)."""
    if target is None:
        target = registry

    document_parser.register(target)
    file_tools.register(target)
    shell_tool.register(target)
    web_search.register(target)
    web_fetch.register(target)
    todowrite.register(target)
    notify.register(target)
    task_tool.register(target)
