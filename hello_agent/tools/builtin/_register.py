"""Register all builtin tools with the shared `registry`.

Idempotent — safe to call multiple times.
"""
from __future__ import annotations

from hello_agent.tools.registry import registry


def register_all() -> None:
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

    document_parser.register(registry)
    file_tools.register(registry)
    shell_tool.register(registry)
    web_search.register(registry)
    web_fetch.register(registry)
    todowrite.register(registry)
    notify.register(registry)
    task_tool.register(registry)
