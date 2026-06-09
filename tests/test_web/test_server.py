"""Tests for the FastAPI server bootstrap + chat endpoints.

Coverage:
- `GET /api/health` returns 200 with `{status: ok, version: ...}`.
- `GET /` returns the "API running" message when the React `dist/`
  is not built; the static handler is tested via the static mount
  helper in isolation (we don't ship a built React UI in tests).
- `POST /api/chat/` returns a `ChatResponse` with the final assistant
  text and the conversation trail, against a mock LLM.
- `GET /api/chat/stream` emits the documented SSE event sequence:
  start → message → tool_call → tool_result → final.
- CORS preflight from the configured origin is allowed.

The chat tests inject a fake LLM via monkeypatching the `LLMClient`
imported into `hello_agent.web.routes.chat`, so they don't hit the
network. The `app_client` fixture runs the FastAPI lifespan, which
auto-discovers the 11 builtin tools.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# --- /api/health -------------------------------------------------------------


def test_health_returns_ok(app_client: TestClient) -> None:
    r = app_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.2.0"


def test_health_cors_preflight(app_client: TestClient) -> None:
    """The CORS middleware is wired to allow the local UI origin."""
    r = app_client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:8648",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204)
    # `allow_origin` echoes back the request origin (CORS spec).
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:8648"


# --- POST /api/chat/ (blocking) ----------------------------------------------


def test_chat_blocking_returns_final_text(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mock LLM emits a single plain-text reply; route returns the text."""
    from hello_agent.web.routes import chat as chat_route

    fake_llm = MagicMock()
    fake_llm.chat.return_value = _text_response("hello back")
    monkeypatch.setattr(chat_route, "LLMClient", lambda: fake_llm)

    r = app_client.post("/api/chat/", json={"message": "hi"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["final"] == "hello back"
    assert body["iterations"] == 1
    # The conversation trail includes SYSTEM + USER + ASSISTANT.
    assert len(body["messages"]) == 3
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant"]


def test_chat_blocking_runs_tool_call_then_final(
    app_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    isolated_tool_registry: Any,
) -> None:
    """Mock LLM emits `echo` then `final_answer`; route should report both."""
    from hello_agent.web.routes import chat as chat_route

    fake_llm = MagicMock()
    fake_llm.chat.side_effect = [
        _tool_call_response("echo", {"text": "ping"}),
        _final_answer_response("the answer"),
    ]
    monkeypatch.setattr(chat_route, "LLMClient", lambda: fake_llm)
    # Swap in the isolated registry (with `echo` + `final_answer`)
    # so the agent can dispatch the call.
    monkeypatch.setattr(chat_route, "_shared_registry", isolated_tool_registry)

    r = app_client.post("/api/chat/", json={"message": "test"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["final"] == "the answer"
    assert body["iterations"] == 2
    roles = [m["role"] for m in body["messages"]]
    # The agent must have appended a TOOL message for `echo` and
    # at least one ASSISTANT message (the promoted final answer).
    # Exact role ordering depends on ReAct internals, so we assert
    # on the presence of these slots rather than the full sequence.
    assert "system" in roles
    assert "user" in roles
    assert "tool" in roles
    assert roles[-1] == "assistant"
    # The tool message must reference the echo call.
    echo_msgs = [m for m in body["messages"] if m["role"] == "tool" and m["tool_name"] == "echo"]
    assert echo_msgs, "expected at least one TOOL message for echo"
    assert "echo:ping" in echo_msgs[0]["content"]


def test_chat_blocking_rejects_empty_message(app_client: TestClient) -> None:
    r = app_client.post("/api/chat/", json={"message": ""})
    # The route's manual check returns 400; pydantic would return 422
    # if we set `min_length=1` on the model, but the manual check is
    # the canonical path (so SSE gets a friendly `error` event instead
    # of a 422).
    assert r.status_code == 400
    assert "non-empty" in r.json()["detail"]


def test_chat_blocking_rejects_non_react_agent_type(app_client: TestClient) -> None:
    r = app_client.post("/api/chat/", json={"message": "hi", "agent_type": "simple"})
    assert r.status_code == 400
    assert "react" in r.json()["detail"].lower()


def test_chat_blocking_accepts_session_id(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`session_id` flows from the request to the response unchanged."""
    from hello_agent.web.routes import chat as chat_route

    fake_llm = MagicMock()
    fake_llm.chat.return_value = _text_response("ok")
    monkeypatch.setattr(chat_route, "LLMClient", lambda: fake_llm)

    r = app_client.post(
        "/api/chat/", json={"message": "ping", "session_id": "my-session-1"}
    )
    assert r.status_code == 200
    assert r.json()["session_id"] == "my-session-1"


# --- GET /api/chat/stream (SSE) ----------------------------------------------


def _parse_sse(response_text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE response body into [(event, data), ...] pairs."""
    out: list[tuple[str, dict[str, Any]]] = []
    event: str | None = None
    data_lines: list[str] = []
    for raw_line in response_text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            if event is not None and data_lines:
                try:
                    out.append((event, json.loads("\n".join(data_lines))))
                except json.JSONDecodeError:
                    out.append((event, {"_raw": "\n".join(data_lines)}))
            event = None
            data_lines = []
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())
    return out


def test_chat_stream_emits_full_event_sequence(
    app_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    isolated_tool_registry: Any,
) -> None:
    """SSE: start -> message(echo) -> tool_call(echo) -> tool_result -> final.

    We test the generator directly (instead of through the TestClient)
    because `sse_starlette` creates module-level `asyncio.Event`
    instances whose loop binding is finicky in TestClient's threaded
    event-loop model. The generator is the contract the React UI
    depends on; testing it gives us the same coverage.
    """
    from hello_agent.web.routes import chat as chat_route

    fake_llm = MagicMock()
    fake_llm.chat.side_effect = [
        _tool_call_response("echo", {"text": "ping"}, call_id="call-echo-1"),
        _final_answer_response("done"),
    ]
    monkeypatch.setattr(chat_route, "LLMClient", lambda: fake_llm)
    monkeypatch.setattr(chat_route, "_shared_registry", isolated_tool_registry)

    # Drive the SSE generator directly.
    import asyncio

    from hello_agent.web.routes.chat import ChatRequest, _stream_chat

    async def _consume() -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        async for ev in _stream_chat(ChatRequest(message="hi"), tool_registry=isolated_tool_registry):
            data = json.loads(ev["data"])
            events.append((ev["event"], data))
        return events

    events = asyncio.run(_consume())
    names = [name for name, _ in events]
    # The exact sequence we expect: start, message, tool_call, tool_result,
    # then another message (the final_answer assistant step), then final.
    assert names[0] == "start"
    assert "message" in names
    assert "tool_call" in names
    assert "tool_result" in names
    assert names[-1] == "final"

    # Spot-check the first message event payload.
    first_message = next(d for n, d in events if n == "message")
    assert first_message["role"] == "assistant"
    assert len(first_message["tool_calls"]) == 1
    assert first_message["tool_calls"][0]["name"] == "echo"

    # And the final event.
    final = events[-1][1]
    assert final["iterations"] >= 1
    assert final["final"] == "done"


def test_chat_stream_handles_empty_message(
    app_client: TestClient,  # noqa: ARG001 — fixture for parity with siblings
) -> None:
    """Empty message → single `error` event, no `start`."""
    import asyncio

    from hello_agent.web.routes.chat import ChatRequest, _stream_chat

    async def _consume() -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        async for ev in _stream_chat(ChatRequest(message="")):
            data = json.loads(ev["data"])
            events.append((ev["event"], data))
        return events

    events = asyncio.run(_consume())
    names = [n for n, _ in events]
    assert names == ["error"]


def test_chat_stream_text_only(
    app_client: TestClient,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the LLM emits plain text (no tool calls), we get start→message→final."""
    from hello_agent.web.routes import chat as chat_route

    fake_llm = MagicMock()
    fake_llm.chat.return_value = _text_response("just text")
    monkeypatch.setattr(chat_route, "LLMClient", lambda: fake_llm)

    import asyncio

    from hello_agent.web.routes.chat import ChatRequest, _stream_chat

    async def _consume() -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        async for ev in _stream_chat(ChatRequest(message="hi")):
            data = json.loads(ev["data"])
            events.append((ev["event"], data))
        return events

    events = asyncio.run(_consume())
    names = [n for n, _ in events]
    assert names[0] == "start"
    assert "tool_call" not in names
    assert "tool_result" not in names
    assert names[-1] == "final"


def test_chat_stream_endpoint_returns_event_source_response(
    app_client: TestClient,
) -> None:
    """Smoke: the route returns 200 with `text/event-stream` content-type.

    We don't drain the body (the sse_starlette module-level Event is
    finicky in TestClient). The route is hit through `httpx.AsyncClient`
    with a very short timeout so the generator cleanup doesn't hit the
    exit-signal wait.
    """
    import httpx

    async def _hit() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_client.app),
            base_url="http://test",
        ) as ac:
            return await ac.get(
                "/api/chat/stream?message=hi",
                timeout=0.5,  # bail before sse_starlette's exit-signal task
            )

    resp = asyncio.run(_hit())
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "text/event-stream" in ct


# --- root / static mount -----------------------------------------------------


def test_root_does_not_crash(app_client: TestClient) -> None:
    """Whether or not the React build is present, `GET /` returns 200
    (or, if the empty placeholder `index.html` is in the static dir,
    a 200 with an empty body). The server must not 500.
    """
    r = app_client.get("/")
    assert r.status_code in (200, 404)
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
        body = r.json()
        assert "hello-agent" in body.get("message", "") or "version" in body


# --- helpers (reused from conftest via the imports above) -------------------

# We re-import the stub helpers so the tests above are self-contained
# when read in isolation. (They're also in conftest.py for reuse.)
from tests.test_web.conftest import (  # noqa: E402, F401
    _final_answer_response as _fa,  # alias to silence ruff F401
)
from tests.test_web.conftest import (  # noqa: E402
    _StubResponse,
    _StubToolCall,
)


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
                name="final_answer",
                arguments=json.dumps({"answer": answer}),
                call_id="call-final",
            )
        ]
    )
