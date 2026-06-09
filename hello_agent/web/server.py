"""Web UI backend — FastAPI app factory.

Implements the `hello_agent.web.server` module that `cli/serve.py`
imports (`from hello_agent.web.server import create_app`) and that
`uvicorn` targets by default (`uvicorn hello_agent.web.server:app`).

The factory is intentionally side-effect-free at *call time*: building
the `FastAPI` instance reads the config singleton + walks the tool
registry, but does not start any background workers. Long-lived
background work (SSE connections, in-process session store) is owned
by the route modules.

The `app` module-level singleton is created lazily on first import by
calling `create_app()` with no arguments.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from hello_agent.core.config import get_env
from hello_agent.core.logging import get_logger
from hello_agent.web.routes import chat, config, sessions, skills, tools

__version__ = "0.2.0"

logger = get_logger(__name__)

# Path to the directory where the React build output lives.
STATIC_DIR: Path = Path(__file__).resolve().parent / "static"


def mount_static(app: FastAPI, static_dir: Path | None = None) -> bool:
    """Mount `static_dir` (default: `hello_agent/web/static/`) at `/`.

    Returns True if a directory was mounted, False if `static_dir` is
    missing or empty (in which case the API is still served, but the
    React UI is unavailable — typically because `npm run build` hasn't
    been run yet).

    FastAPI walks routes before static files, so the `/api/*` routers
    always win over the static handler.
    """
    target = static_dir or STATIC_DIR
    if not target.is_dir():
        return False
    # `html=True` makes the StaticFiles middleware serve index.html for
    # unknown paths (SPA-style fallback so React Router can take over).
    app.mount("/", StaticFiles(directory=str(target), html=True), name="static")
    return True


def _bootstrap_tooling() -> None:
    """Side-effect: discover builtin tools + register the `default` toolset.

    Called from the FastAPI lifespan so the Web UI starts with the full
    toolset ready. Idempotent: `ToolRegistry.auto_discover` and
    `register_toolset` both short-circuit on repeat calls.
    """
    try:
        from hello_agent.tools import toolsets as _toolsets
        from hello_agent.tools.registry import registry as _shared_registry

        _shared_registry.auto_discover()
        _toolsets.bootstrap_toolsets()
        logger.info("tool registry bootstrapped ({} tools)", len(_shared_registry.list_all()))
    except Exception as exc:  # noqa: BLE001
        # Don't crash the server if a builtin fails to import — log
        # loudly and continue. The user can still call `/api/health` and
        # the API surface that doesn't need tools.
        logger.warning("tooling bootstrap failed: {}", exc)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: bootstrap the tool registry on startup, no-op on shutdown."""
    _bootstrap_tooling()
    yield


def create_app(*, mount_static_dir: Path | None = None) -> FastAPI:
    """Build a FastAPI app with all routes + CORS + static mount."""
    env = get_env()
    app = FastAPI(
        title="hello-agent Web UI",
        version=__version__,
        description=(
            "Local Web UI for hello-agent. "
            f"Default listen: http://{env.web_host}:{env.web_port}"
        ),
        lifespan=_lifespan,
    )

    # CORS: only allow the local UI origin by default. The default port
    # is 8648 (per `EnvSettings.web_port`). We allow the configured port
    # AND 5173 (Vite dev-server default) so a developer running
    # `npm run dev` against the same backend works out of the box.
    allowed_origins = [
        f"http://127.0.0.1:{env.web_port}",
        f"http://localhost:{env.web_port}",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routers. Prefixes match `docs/ENGINEERING.md` §7.4.3.
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
    app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
    app.include_router(tools.router, prefix="/api/tools", tags=["tools"])
    app.include_router(config.router, prefix="/api/config", tags=["config"])

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Liveness probe used by the SPA + tray autostart monitoring."""
        return {"status": "ok", "version": __version__}

    mounted = mount_static(app, mount_static_dir)
    if not mounted:
        logger.info("static dir missing — UI will be API-only: {}", STATIC_DIR)

        @app.get("/")
        async def root_no_ui() -> dict[str, str]:
            return {
                "message": (
                    "hello-agent API is running. "
                    "Build the React UI with `cd web-ui && npm install && npm run build`."
                ),
                "version": __version__,
            }

    return app


# Module-level default for `uvicorn hello_agent.web.server:app`.
app = create_app()


__all__ = ["app", "create_app", "mount_static", "STATIC_DIR", "__version__"]
