"""Chat routes — blocking POST + SSE streaming.

The chat route is the *front door* of the agent. The blocking POST is
trivial: run the agent, return the final state. The SSE stream is the
real product surface — it emits an event for every meaningful
state transition so the React UI can render streamed tokens, tool
calls, tool results, and the final answer without polling.

SSE event types (matched on the React side in `useChatStream`):

- `start`       — `{"session_id": "..."}` — sent once at the beginning.
- `message`     — `{"role": "assistant", "content": "...",
                    "tool_calls": [{id, name, arguments}],
                    "finish_reason": "..."}` — one per LLM step.
- `tool_call`   — `{"id": "...", "name": "...", "arguments": {...}}`
                   — convenience copy of the LLM's tool call so the
                   UI can render a `<ToolCallCard>` as soon as the
                   call is dispatched, not after the result lands.
- `tool_result` — `{"tool_call_id": "...", "name": "...",
                    "content": "...", "is_error": bool}` — the
                   final answer from the tool dispatcher.
- `error`       — `{"message": "...", "type": "..."}` — emitted
                   when the agent raises; the connection then closes.
- `final`       — `{"iterations": int, "session_id": "..."}` — last
                   event; client knows the turn is done.

The ReAct agent is reused unmodified (see `hello_agent.agents.react`).
We construct a fresh `AgentState` for each request, run the loop
ourselves (mirroring the TUI's `_run_one_repl`) so we can intercept
each step and emit an SSE event.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from hello_agent.agents.react import ReActAgent
from hello_agent.core.config import get_config
from hello_agent.core.llm import LLMClient
from hello_agent.core.logging import get_logger
from hello_agent.core.types import AgentState, Message, Role
from hello_agent.tools.registry import ToolRegistry
from hello_agent.tools.registry import registry as _shared_registry

logger = get_logger(__name__)

router = APIRouter()


# ----- request / response shapes ---------------------------------------------


class ChatRequest(BaseModel):
    """Body for `POST /api/chat/`.

    `stream` is honoured by the blocking endpoint too — when True, the
    response is still a single JSON blob (with the full conversation
    trail in `messages`) but the server-side agent still streams tool
    calls internally. Use the SSE endpoint for true per-token
    streaming; the blocking endpoint exists for headless tests + CLI
    integrations.
    """

    message: str = Field(..., max_length=64_000)
    session_id: str | None = None
    agent_type: str | None = None
    stream: bool = False


class ChatMessagePayload(BaseModel):
    """One history message in the blocking response."""

    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    name: str | None = None


class ChatResponse(BaseModel):
    """Body returned by `POST /api/chat/`."""

    session_id: str
    iterations: int
    final: str
    messages: list[ChatMessagePayload]
    interrupted: bool = False


# ----- helpers ----------------------------------------------------------------


def _build_agent(
    session_id: str | None = None,
    agent_type: str | None = None,
    tool_registry: ToolRegistry | None = None,
) -> ReActAgent:
    """Construct a ReAct agent with default settings.

    `tool_registry` defaults to the shared `hello_agent.tools.registry.registry`
    (the one populated by `@tool` and the builtin bootstrap). Tests pass
    their own isolated registry.
    """
    cfg = get_config()
    atype = (agent_type or cfg.agent.default_type or "react").lower()
    if atype != "react":
        # For v0.2 Day 8 we only ship the ReAct SSE surface. Other agent
        # types (simple/plan_solve/reflection) are not wired into the
        # SSE path because their `step()` signatures differ; they still
        # work via the CLI.
        raise HTTPException(
            status_code=400,
            detail=f"SSE chat is ReAct-only; got agent_type={atype!r}",
        )
    llm = LLMClient()
    system_prompt = (
        "You are hello-agent, a personal Windows Python agent. "
        "Be concise. Use tools when they help. Remember user preferences across the session."
    )
    return ReActAgent(
        llm=llm,
        tool_registry=tool_registry or _shared_registry,
        system_prompt=system_prompt,
        max_iterations=cfg.agent.max_iterations,
        max_cost_per_turn_usd=cfg.agent.max_cost_per_turn_usd,
        session_id=session_id,
    )


def _serialize_state(state: AgentState) -> list[ChatMessagePayload]:
    """Convert an `AgentState` into a list of wire-shaped messages."""
    out: list[ChatMessagePayload] = []
    for m in state.messages:
        out.append(
            ChatMessagePayload(
                role=m.role.value,
                content=m.content,
                tool_calls=[tc.__dict__ for tc in m.tool_calls] if m.tool_calls else None,
                tool_call_id=m.tool_call_id,
                tool_name=m.tool_name,
                name=m.name,
            )
        )
    return out


def _find_last_assistant_text(state: AgentState) -> str:
    """Return the most recent assistant text in `state` (empty string if none)."""
    for m in reversed(state.messages):
        if m.role == Role.ASSISTANT and m.content:
            return m.content
    return ""


# ----- POST /api/chat/ (blocking) --------------------------------------------


@router.post("/", response_model=ChatResponse)
async def chat_blocking(req: ChatRequest) -> ChatResponse:
    """Run one ReAct turn and return the full state as JSON.

    The blocking endpoint is intended for headless / scripted use; the
    React UI uses the SSE endpoint so it can stream per-token events.
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must be non-empty")
    try:
        agent = _build_agent(session_id=req.session_id, agent_type=req.agent_type)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — surface as 500
        logger.exception("chat: failed to build agent")
        raise HTTPException(status_code=500, detail=f"agent init: {exc}") from exc

    try:
        state = agent.run(req.message)
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat: agent.run failed")
        raise HTTPException(status_code=500, detail=f"agent run: {exc}") from exc

    return ChatResponse(
        session_id=state.session_id,
        iterations=state.iteration,
        final=_find_last_assistant_text(state),
        messages=_serialize_state(state),
        interrupted=state.interrupted,
    )


# ----- GET /api/chat/stream (SSE) --------------------------------------------


def _sse(event: str, data: dict[str, Any]) -> dict[str, str]:
    """Format a single SSE event with a JSON `data` payload."""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)}


async def _run_step(agent: ReActAgent, state: AgentState) -> AgentState:
    """Run a single `agent.step()` in the default executor.

    The ReAct agent is sync (it calls the sync `LLMClient`). We push it
    to a worker thread so the SSE event loop stays responsive.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, agent.step, state)


async def _stream_chat(
    req: ChatRequest, tool_registry: ToolRegistry | None = None
) -> AsyncIterator[dict[str, str]]:
    """Yield SSE events for one chat turn.

    The flow mirrors `chat_app._run_one_repl` from the CLI: build the
    state, run the loop step-by-step, emit an event per step, dispatch
    tools when the assistant requests them, and finally emit a `final`
    event with the iteration count.
    """
    if not req.message.strip():
        yield _sse("error", {"type": "ValueError", "message": "message must be non-empty"})
        return

    try:
        agent = _build_agent(
            session_id=req.session_id, agent_type=req.agent_type, tool_registry=tool_registry
        )
    except HTTPException as exc:
        yield _sse("error", {"type": "BadRequest", "message": str(exc.detail)})
        return
    except Exception as exc:  # noqa: BLE001
        yield _sse("error", {"type": type(exc).__name__, "message": str(exc)})
        return

    state = AgentState(
        session_id=agent.session_id,
        messages=[
            Message(role=Role.SYSTEM, content=agent.system_prompt),
            Message(role=Role.USER, content=req.message),
        ],
        max_iterations=agent.max_iterations,
    )
    yield _sse("start", {"session_id": state.session_id})

    iterations = 0
    try:
        for _ in range(agent.max_iterations):
            try:
                # `prev_len` lets us detect which messages the agent
                # appended on this step. ReAct's `step()` does the
                # assistant-message AND the tool dispatch in one shot,
                # so the tail of `state.messages` after the call is
                # [ASSISTANT, TOOL?, ASSISTANT(promoted-final)?].
                prev_len = len(state.messages)
                state = await _run_step(agent, state)
            except Exception as exc:  # noqa: BLE001
                logger.exception("stream_chat: step failed")
                yield _sse("error", {"type": type(exc).__name__, "message": str(exc)})
                return
            iterations += 1
            new_msgs = state.messages[prev_len:]
            for m in new_msgs:
                if m.role == Role.ASSISTANT:
                    payload: dict[str, Any] = {
                        "role": m.role.value,
                        "content": m.content or "",
                        "tool_calls": [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in (m.tool_calls or [])
                        ],
                        "finish_reason": m.finish_reason,
                    }
                    yield _sse("message", payload)
                    # Mirror each tool call as its own event so the UI
                    # can render a `<ToolCallCard>` immediately, even
                    # before the result lands.
                    for tc in m.tool_calls or []:
                        yield _sse(
                            "tool_call",
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                        )
                elif m.role == Role.TOOL:
                    yield _sse(
                        "tool_result",
                        {
                            "tool_call_id": m.tool_call_id or "",
                            "name": m.tool_name or "",
                            "content": m.content or "",
                            "is_error": False,
                        },
                    )
            if agent._is_terminal(state):
                break
    except asyncio.CancelledError:
        # Client disconnected mid-stream. Re-raise so the connection
        # cleanly tears down (FastAPI handles the rest).
        raise
    except Exception as exc:  # noqa: BLE001 — belt-and-braces safety net
        yield _sse("error", {"type": type(exc).__name__, "message": str(exc)})
        return

    yield _sse(
        "final",
        {
            "iterations": iterations,
            "session_id": state.session_id,
            "final": _find_last_assistant_text(state),
        },
    )


@router.get("/stream")
async def chat_stream(
    message: str,
    session_id: str | None = None,
    agent_type: str | None = None,
) -> EventSourceResponse:
    """SSE version of `/api/chat/`.

    Query params (FastAPI handles URL-decoding):
    - `message`     — the user prompt
    - `session_id`  — optional; auto-generated if absent
    - `agent_type`  — `react` only for v0.2 (others return an `error` event)
    """
    req = ChatRequest(
        message=message,
        session_id=session_id,
        agent_type=agent_type,
        stream=True,
    )
    return EventSourceResponse(_stream_chat(req), ping=0)


# Re-exported for the test suite (test_routes wires an isolated registry).
__all__ = [
    "router",
    "ChatRequest",
    "ChatResponse",
    "ChatMessagePayload",
    "_build_agent",
    "_stream_chat",
    "_serialize_state",
    "_find_last_assistant_text",
]
