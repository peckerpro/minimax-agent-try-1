"""Shared fixtures for the web (FastAPI) test suite.

The tests need:
- A `TestClient` with a fully-wired app
- A monkey-patchable `LLMClient` so chat tests don't hit the network
- A clean `ToolRegistry` so tool tests don't pollute each other
- An isolated `$HELLO_AGENT_HOME` so config + skills + episodic
  tests don't leak state between tests
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from hello_agent.agents.react import FINAL_ANSWER_TOOL
from hello_agent.core.types import ToolDefinition, ToolResult
from hello_agent.tools.registry import ToolRegistry
from hello_agent.tools.registry import registry as _shared_registry

# --- helpers -----------------------------------------------------------------


class _StubToolCall:
    """Mimics the openai SDK's tool_call shape (subset)."""

    def __init__(self, name: str, arguments: str, call_id: str) -> None:
        self.id = call_id
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = arguments


class _StubMessage:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[_StubToolCall] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class _StubChoice:
    def __init__(
        self,
        content: str | None,
        tool_calls: list[_StubToolCall] | None,
        finish_reason: str = "stop",
    ) -> None:
        self.message = _StubMessage(content=content, tool_calls=tool_calls)
        self.finish_reason = finish_reason


class _StubResponse:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[_StubToolCall] | None = None,
        usage: Any = None,
    ) -> None:
        self.choices = [
            _StubChoice(content=content, tool_calls=tool_calls, finish_reason="stop")
        ]
        # ReAct touches `response.usage.total_tokens`. Provide a stand-in
        # with a `total_tokens` attribute so the code path doesn't blow up
        # in tests that don't care about token accounting.
        self.usage = usage if usage is not None else _StubUsage()


@dataclass
class _StubUsage:  # noqa: B903 — test stub, dataclass for clarity
    total_tokens: int = 0


def _text_response(content: str) -> _StubResponse:
    return _StubResponse(content=content)


def _tool_call_response(name: str, args: dict[str, Any], call_id: str = "call-1") -> _StubResponse:
    return _StubResponse(
        tool_calls=[
            _StubToolCall(name=name, arguments=json.dumps(args), call_id=call_id)
        ]
    )


def _final_answer_response(answer: str) -> _StubResponse:
    return _StubResponse(
        tool_calls=[
            _StubToolCall(
                name=FINAL_ANSWER_TOOL,
                arguments=json.dumps({"answer": answer}),
                call_id="call-final",
            )
        ]
    )


# --- fixtures ----------------------------------------------------------------


@pytest.fixture()
def isolated_tool_registry() -> Iterator[ToolRegistry]:
    """A fresh `ToolRegistry` with `echo` + `final_answer` tools registered.

    Used by tests that build a `ReActAgent` with their own registry
    (so they don't need a real LLM or the full builtin set).
    """
    reg = ToolRegistry()
    reg.register(
        name=FINAL_ANSWER_TOOL,
        toolset="smoke",
        schema=ToolDefinition(
            name=FINAL_ANSWER_TOOL,
            description="Submit the final answer.",
            parameters={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        ),
        handler=lambda args, **kw: ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=str(args.get("answer", "")),
        ),
    )
    reg.register(
        name="echo",
        toolset="smoke",
        schema=ToolDefinition(
            name="echo",
            description="Echo the input.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        handler=lambda args, **kw: ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=f"echo:{args.get('text', '')}",
        ),
    )
    yield reg


@pytest.fixture()
def mock_llm_factory() -> Any:
    """A factory that returns a `MagicMock` LLMClient with pre-canned responses.

    Usage::

        def test_x(mock_llm_factory):
            llm = mock_llm_factory([_tool_call_response("echo", {"text": "x"}),
                                    _text_response("done")])
            # patch hello_agent.web.routes.chat.LLMClient
            monkeypatch.setattr(chat_routes, "LLMClient", lambda: llm)
    """
    responses: list[_StubResponse] = []

    def _factory(planned: list[_StubResponse] | None = None) -> MagicMock:
        responses.clear()
        if planned:
            responses.extend(planned)
        llm = MagicMock()
        if responses:
            llm.chat.side_effect = list(responses)
        else:
            llm.chat.return_value = _text_response("(no response)")
        return llm

    return _factory


@pytest.fixture()
def app_client(tmp_hello_agent_home: object) -> Iterator[TestClient]:
    """A `TestClient` whose app has the lifespan-driven tool bootstrap.

    Uses the `tmp_hello_agent_home` fixture so tests can write files
    to `$HELLO_AGENT_HOME` without leaking.
    """
    # Importing inside the fixture so the app is rebuilt fresh per test
    # (the module-level `app` is shared and we want a clean registry).
    from hello_agent.web import create_app

    # `with TestClient(...)` enters the FastAPI lifespan, which calls
    # `_bootstrap_tooling()` and registers the 11 builtins.
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture(autouse=True)
def _reset_shared_registry_state() -> Iterator[None]:
    """After every test, restore the shared registry to "empty" state.

    The lifespan in `app_client` enables all 11 builtins; tests that
    *disable* a tool would leave it disabled for the next test if we
    didn't clean up. Idempotent: re-enabling an enabled tool is a no-op.
    """
    yield
    try:
        names = [t.name for t in _shared_registry.list_all()]
        if names:
            _shared_registry.enable(names)
    except Exception:  # noqa: BLE001
        pass
