"""Web UI: FastAPI backend + React static frontend.

Public surface:
- `create_app()` — factory that returns a wired `FastAPI` instance
- `app`          — module-level default (built once at import)
- `mount_static` — helper used by tests + uvicorn reload
- `STATIC_DIR`   — default path for the React build output
- `__version__`  — the package version (mirrored from `hello_agent.__version__`)
"""
from __future__ import annotations

# `hello_agent.web.server` is the source of truth for `app`; we re-export
# it here so callers can write `from hello_agent.web import app`.
from hello_agent.web.server import (
    STATIC_DIR,
    __version__,
    app,
    create_app,
    mount_static,
)

__all__ = ["app", "create_app", "mount_static", "STATIC_DIR", "__version__"]
