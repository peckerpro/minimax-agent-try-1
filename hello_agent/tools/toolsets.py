"""Toolset definitions.

A toolset is a named bundle of tools. Agents can be configured to use a
specific toolset. v0.1 ships the `default` toolset only; additional toolsets
can be added without code changes by listing tool names in config.yaml.
"""
from __future__ import annotations

from hello_agent.tools.registry import registry


def bootstrap_toolsets() -> None:
    """Register the canonical toolset bundles.

    Called from the CLI entry point and from the FastAPI server bootstrap.
    Idempotent — re-registering is a no-op because we just re-write the list.
    """
    default_tools = [
        "file_tools.read_file",
        "file_tools.write_file",
        "file_tools.edit_file",
        "shell_tool.run_powershell",
        "shell_tool.run_cmd",
        "web_search.search",
        "web_fetch.fetch",
        "document_parser.parse_document",
        "todowrite.todowrite",
        "notify.notify",
    ]
    # We register by simple short name — the registry uses the *tool* name,
    # not qualified name. Filter to ones that are actually registered.
    available = {t.name for t in registry.list_all()}
    short_names = [n.split(".")[-1] for n in default_tools if n.split(".")[-1] in available]
    registry.register_toolset("default", short_names)
