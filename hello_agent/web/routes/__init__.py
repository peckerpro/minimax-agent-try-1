"""Web UI route modules.

Each submodule owns a slice of `/api/*`:

- `chat`     — `POST /api/chat/` (blocking) + `GET /api/chat/stream` (SSE)
- `sessions` — session list / detail / resume (queries episodic memory)
- `skills`   — skill list / detail / install (multipart upload)
- `tools`    — tool list / enable / disable
- `config`   — get / put `config.yaml` (full config in/out as JSON)

All routers are re-exported here so callers can write
`from hello_agent.web.routes import chat` and the FastAPI app does
`include_router(chat.router, prefix="/api/chat")`.
"""
from __future__ import annotations

from hello_agent.web.routes import chat, config, sessions, skills, tools

__all__ = ["chat", "config", "sessions", "skills", "tools"]
