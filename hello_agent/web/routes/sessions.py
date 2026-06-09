"""Sessions route — list / detail / resume.

A "session" in v0.2 is the row pair in `episodic.episodes`: a
`session_id` and a summary. The chat endpoints auto-create a session
when the user sends the first message; the Web UI surfaces those
sessions in the sidebar.

`POST /api/sessions/{id}/resume` does *not* re-run the conversation;
it just marks the session as the "active" one for the running server.
The actual resumption happens client-side by passing the `session_id`
to the next `POST /api/chat/` (which then hydrates `AgentState.messages`
from the episodic store — Day 9+ work; for v0.2 the agent rebuilds from
the user prompt).
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hello_agent.core.logging import get_logger
from hello_agent.memory.episodic import EpisodicMemory

logger = get_logger(__name__)

router = APIRouter()


# ----- helpers ---------------------------------------------------------------


def _open_episodic() -> Iterator[EpisodicMemory]:
    """Yield a fresh `EpisodicMemory` and close it on exit.

    Used as a context manager style helper for the route handlers. We
    avoid module-level state because uvicorn workers can fork.
    """
    em = EpisodicMemory()
    try:
        yield em
    finally:
        em.close()


class SessionSummary(BaseModel):
    id: int
    session_id: str
    summary: str
    created_at: str
    message_count: int = 0  # every row in episodes = 1 summary message


class SessionDetail(BaseModel):
    session_id: str
    messages: list[dict[str, Any]]


class ResumeResponse(BaseModel):
    session_id: str
    resumed: bool
    message_count: int
    note: str = ""


# ----- routes ----------------------------------------------------------------


@router.get("/", response_model=list[SessionSummary])
async def list_sessions(limit: int = 50) -> list[SessionSummary]:
    """Return the most-recent sessions (across all session_ids, newest first)."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be in [1, 500]")
    with _open_episodic() as em:
        rows = em.list_recent(limit=limit)
    out: list[SessionSummary] = []
    for r in rows:
        out.append(
            SessionSummary(
                id=int(r["id"]),
                session_id=r["session_id"],
                summary=r["summary"],
                created_at=r["created_at"],
                message_count=1,  # each row is one summary
            )
        )
    return out


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str) -> SessionDetail:
    """Return every episode (summary row) for one session, oldest first."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    with _open_episodic() as em:
        rows = em.list_recent(limit=500, session_id=session_id)
    # list_recent returns DESC; flip to ASC for the UI's natural reading order.
    rows.reverse()
    return SessionDetail(
        session_id=session_id,
        messages=[dict(r) for r in rows],
    )


@router.post("/{session_id}/resume", response_model=ResumeResponse)
async def resume_session(session_id: str) -> ResumeResponse:
    """Mark a session as 'active' for the next chat turn.

    v0.2 stores the resumption in process memory (`_active_session`).
    A future Day-9+ iteration will hydrate `AgentState.messages` from
    the episodic log; for now the client just passes the `session_id`
    in subsequent `POST /api/chat/` calls.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    with _open_episodic() as em:
        rows = em.list_recent(limit=500, session_id=session_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"no episodes for session {session_id!r}")
    # Mark as active in the in-process registry (Day 8 stub).
    global _active_session
    _active_session = session_id
    return ResumeResponse(
        session_id=session_id,
        resumed=True,
        message_count=len(rows),
        note="next chat turn will use this session_id",
    )


# v0.2 in-process "active session" — a Day-9+ refactor will move this
# into a session manager that hydrates `AgentState.messages`.
_active_session: str | None = None


def get_active_session() -> str | None:
    """Module-level helper used by tests + the chat route."""
    return _active_session


def reset_active_session() -> None:
    """Test helper — drop the in-process active session."""
    global _active_session
    _active_session = None


__all__ = [
    "router",
    "SessionSummary",
    "SessionDetail",
    "ResumeResponse",
    "get_active_session",
    "reset_active_session",
]
