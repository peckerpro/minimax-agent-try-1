# Tool Authoring Guide

> Author and ship your own tools for `hello-agent-2`. This document walks
> through `@tool` registration, custom JSON schemas, confirmation-gated
> ("dangerous") tools, unit testing, and distribution as a plugin.

Tools are how the ReAct agent touches the outside world. The registry
(`hello_agent.tools.registry`) is the single source of truth: the agent
queries it for `tools/list` (passed to the LLM as `tools=[...]`) and
routes `tools/call` requests to the registered handler.

---

## 1. Anatomy of a tool

Every tool is a thin object with three pieces:

| Piece | What it is | Where it goes |
| --- | --- | --- |
| **Schema** | JSON-Schema dict (`name`, `description`, `parameters`) | `ToolDefinition` |
| **Handler** | Sync callable: `(args: dict, **kw) -> ToolResult` | `registry.register(...)` |
| **Optional `check_fn`** | Returns True iff the tool is usable right now | `check_fn=` |

The handler must return a `hello_agent.core.types.ToolResult`:

```python
from hello_agent.core.types import ToolResult
ToolResult(tool_call_id="", content="...", is_error=False)
```

The `content` is what gets fed back to the LLM as a `tool` message — a
**string**. JSON-serialize structured data.

---

## 2. The `@tool` decorator (recommended)

For the common case — a stateless function with primitive typed args —
use the `@tool` decorator in `hello_agent.tools.base`:

```python
from hello_agent.tools.base import tool

@tool(
    name="greet",
    toolset="greetings",
    description="Say hello in the user's preferred language.",
)
def greet(language: str, name: str) -> str:
    """Return a greeting in the requested language."""
    greetings = {"en": "Hello", "ja": "こんにちは", "zh": "你好"}
    head = greetings.get(language, greetings["en"])
    return f"{head}, {name}!"
```

What the decorator does for you:

1. Builds the JSON Schema from the type hints (`str` → `"type": "string"`,
   `int` → `"type": "integer"`, etc.).
2. Marks the tool default-enabled.
3. Calls `ToolRegistry.register_static(...)` against the shared
   singleton, so it's immediately visible to the ReAct agent.

**Files that call `@tool`** are picked up automatically when the
`ToolRegistry(auto_discover=True)` constructor runs (which the CLI does
on every command). If you ship your tools in a separate Python package,
register them from an `entry_point` (see §6).

### Advanced: list/dict args

The decorator supports `list[X]` and `dict` type hints:

```python
from typing import Optional

@tool(name="find_files", toolset="file_tools")
def find_files(
    pattern: str,
    extensions: Optional[list[str]] = None,
    recursive: bool = True,
) -> str:
    """Find files matching `pattern` under the working directory."""
    ...
```

JSON-Schema fragments produced:

```json
{
  "type": "object",
  "properties": {
    "pattern": {"type": "string"},
    "extensions": {"type": "array", "items": {"type": "string"}},
    "recursive": {"type": "boolean"}
  },
  "required": ["pattern", "recursive"]
}
```

---

## 3. Manual registration (for non-trivial tools)

When you need full control over the schema or want to wire a non-function
callable (e.g. an instance method that closes over state), drop the
decorator and call `registry.register(...)` directly:

```python
from hello_agent.core.types import ToolDefinition, ToolResult
from hello_agent.tools.registry import ToolRegistry


class TodoStore:
    def __init__(self) -> None:
        self._items: list[str] = []

    def add(self, item: str) -> ToolResult:
        self._items.append(item)
        return ToolResult(
            tool_call_id="",
            content=f"added: {item} (total: {len(self._items)})",
            is_error=False,
        )


def register(registry: ToolRegistry) -> None:
    store = TodoStore()
    registry.register(
        name="todo_add",
        toolset="todowrite",
        schema=ToolDefinition(
            name="todo_add",
            description="Add an item to the in-memory todo list.",
            parameters={
                "type": "object",
                "properties": {"item": {"type": "string"}},
                "required": ["item"],
            },
        ),
        handler=lambda args, **kw: store.add(args["item"]),
    )
```

Conventions:

- `name` — globally unique, snake_case, no spaces.
- `toolset` — grouping key (one registry can hold toolsets like
  `"file_tools"`, `"shell_tool"`, `"greetings"`). The CLI's
  `hello-agent tools list` groups by toolset.
- `description` — short, imperative, ends with a period. The LLM uses
  this to decide when to call the tool.

---

## 4. Dangerous tools (confirmation gating)

Tools that mutate the user's machine (write files, run shell, etc.)
should set `dangerous=True`. They require explicit confirmation per
session:

```python
registry.register(
    name="write_file",
    toolset="file_tools",
    schema=ToolDefinition(...),
    handler=_write_file_handler,
    dangerous=True,
)
```

Runtime contract:

- The ReAct agent checks `check_permission(tool_name, session_id)` before
  every call (see `hello_agent.tools.permission`).
- If the user hasn't confirmed in the current session, the tool returns
  a stringified error `{"error": "tool 'write_file' requires confirmation. Run /confirm write_file..."}`.
- The session confirmation cache lives on the registry itself
  (`ToolRegistry.confirm_dangerous(session_id, tool_name)`).
- Tools listed under `tools.require_confirmation` in `config.yaml`
  always need confirmation; users opt-in to others with `/confirm`.

A dangerous tool SHOULD log the action before executing (Loguru,
`logger.bind(category="tools").info(...)`).

---

## 5. Tool gating via `check_fn`

If a tool depends on an optional package or environment variable, attach
a `check_fn` that returns `True` iff the tool is currently usable. The
registry reports it to the user via `hello-agent tools list` and skips
it during `tools/list` advertised to the LLM when `enabled_only=True`.

```python
def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


@tool(
    name="browser_click",
    toolset="browser",
    description="Click an element on a Playwright-driven browser.",
    check_fn=_playwright_available,
)
def browser_click(selector: str) -> str:
    ...
```

When `check_fn` returns `False`, the tool is filtered out of the
`tools/list` payload sent to the LLM — the model literally cannot call
it. This is the right behavior for "tool exists but isn't usable right
now".

---

## 6. Distributing tools as a plugin

To ship a tool outside the `hello-agent-2` codebase:

### Package layout

```
hello_agent_myplugin/
├── pyproject.toml
└── hello_agent_myplugin/
    ├── __init__.py
    └── tools.py     # imports + registers
```

### Auto-register via entry point

In your `pyproject.toml`:

```toml
[project.entry-points."hello_agent.tools"]
myplugin = "hello_agent_myplugin.tools:register"
```

When the user installs `pip install hello-agent-myplugin`, the plugin's
`register()` is called automatically by
`hello_agent.tools.registry.ToolRegistry.auto_discover()` at every CLI
boot.

### `register()` contract

```python
def register(registry: ToolRegistry | None = None) -> None:
    """Called with the shared registry singleton."""
    from hello_agent.tools.registry import registry as shared
    target = registry or shared
    # ...register your tools...
```

If the registry parameter is `None`, you should fall back to the shared
singleton so that simple `entry_points` scripts don't need to import it.

---

## 7. Testing your tools

A tool's handler is a plain Python function, so unit testing is easy:

```python
from hello_agent.tools.registry import ToolRegistry

def test_greet_english() -> None:
    reg = ToolRegistry()
    from my_plugin.tools import register
    register(reg)

    result = reg.execute("greet", {"language": "en", "name": "Ada"})
    assert result.is_error is False
    assert result.content == "Hello, Ada!"
```

For dangerous tools, confirm first:

```python
def test_write_file_requires_confirmation() -> None:
    reg = ToolRegistry()
    register(reg)

    # Without confirmation, the tool refuses.
    result = reg.execute(
        "write_file",
        {"path": "/tmp/a.txt", "content": "hi"},
        session_id="test-session",
    )
    assert result.is_error is True
    assert "requires confirmation" in result.content

    # After confirmation, the tool runs.
    reg.confirm_dangerous("test-session", "write_file")
    result = reg.execute(
        "write_file",
        {"path": "/tmp/a.txt", "content": "hi"},
        session_id="test-session",
    )
    assert result.is_error is False
```

---

## 8. Worked example — a complete plugin

```python
# hello_agent_myplugin/tools.py
"""hello-agent-myplugin: add a `word_count` tool to hello-agent-2.

Install:    uv pip install hello-agent-myplugin
Verify:     uv run hello-agent tools list | grep word_count
Use:        ask the agent "how many words in my README?"
"""
from __future__ import annotations

from collections.abc import Callable

from hello_agent.core.logging import get_logger
from hello_agent.core.types import ToolDefinition, ToolResult
from hello_agent.tools.registry import ToolRegistry

logger = get_logger(__name__)


def _word_count(args: dict, **_: object) -> ToolResult:
    text = str(args.get("text", ""))
    n = len(text.split())
    return ToolResult(
        tool_call_id="",
        content=f"{n}",
        is_error=False,
    )


def _schema() -> ToolDefinition:
    return ToolDefinition(
        name="word_count",
        description="Count the words in a piece of text.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )


def register(registry: ToolRegistry | None = None) -> None:
    from hello_agent.tools.registry import registry as shared

    target = registry or shared
    target.register(
        name="word_count",
        toolset="text",
        schema=_schema(),
        handler=_word_count,
    )
    logger.bind(category="tools").info("word_count registered")
```

After installing this package, the user can:

```powershell
uv run hello-agent tools list
# ...file_tools, shell_tool, ..., text/word_count

uv run hello-agent chat "How many words are in this README?"
# (the LLM reads README.md via read_file, then calls word_count, then answers)
```

---

## 9. Conventions summary

| Convention | Rule |
| --- | --- |
| **Naming** | `snake_case`, globally unique, no spaces |
| **Description** | One short sentence, imperative mood, ends with `.` |
| **Handler signature** | `(args: dict, **kwargs) -> ToolResult` |
| **Handler content** | Always a `str` — JSON-encode structured data |
| **Dangerous tools** | Set `dangerous=True`; never auto-confirm |
| **Optional tools** | Attach `check_fn`; the LLM won't see it when unavailable |
| **Distribution** | `pyproject.toml` `[project.entry-points."hello_agent.tools"]` |
| **Tests** | Use a per-test `ToolRegistry()` instance; avoid the shared singleton |
| **Logging** | `logger.bind(category="tools").info(...)` for each invocation |
| **Telemetry** | Emit per-call token counts via `count_tokens` if you have them |

For the registry / dispatcher / circuit-breaker internals, see
`docs/ENGINEERING.md` §6.4. For the permission model and confirmation
flow, see §6.4 + `hello_agent/tools/permission.py`.