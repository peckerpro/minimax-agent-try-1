"""One-shot backend launcher — runs uvicorn in the FOREGROUND of THIS process.

Used by the desktop CLI and the `hello-agent start` launcher to spawn
the backend. Written as a module (not a `-c` string) so PowerShell
quoting doesn't fight us, and so stdout/stderr go to the parent
process's handles without any Windows-specific dup2 dance (which
turned out to be unreliable).

Why not `subprocess.Popen(["python", "-m", "uvicorn", ...])`:
    On Windows, the spawned child inherits a different sys.path than
    we expect, and `uv run` adds ~5-10s of overhead on cold start.
    Running uvicorn in-process is the cleanest path that doesn't
    fight the environment.

This module is also runnable directly:
    <venv-python> -m hello_agent._run_backend --host 127.0.0.1 --port 8648
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make sure the package root is on sys.path when invoked as a script.
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8648)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    # Do NOT call _bootstrap_tooling() here — the FastAPI app's
    # `lifespan` handler does it on startup. Calling it twice
    # causes two concurrent registrations to fight over the
    # shared registry lock on Windows.

    import uvicorn  # type: ignore[import-not-found]

    # `log_config=None` keeps uvicorn from overwriting our loguru
    # setup; we still get uvicorn's access lines on stderr.
    config = uvicorn.Config(
        "hello_agent.web.server:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        log_config=None,
    )
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
