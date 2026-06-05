"""Shared pytest fixtures and configuration for the hello-agent test suite.

Important invariants:
  - HELLO_AGENT_PROFILE is set to "test" so the test suite NEVER touches
    the user's real $HELLO_AGENT_HOME (which lives at %LOCALAPPDATA% on
    Windows). All tests work under a temp dir.
  - hello_agent.core.config caches singletons — we call `reload_config()`
    in each test session to flush them after changing env vars.
  - The session-scoped `tmp_hello_agent_home` fixture creates a unique
    temp dir and points HELLO_AGENT_HOME at it for the duration of the
    test session.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolate_hello_agent_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Force all hello_agent paths to a session-scoped temp dir.

    Set HELLO_AGENT_PROFILE=test so paths.get_hello_agent_home() lands in a
    separate sub-tree, and HELLO_AGENT_HOME to an absolute temp dir so we
    don't depend on platform defaults.
    """
    tmp = tmp_path_factory.mktemp("hello_agent_home")
    os.environ["HELLO_AGENT_HOME"] = str(tmp)
    os.environ["HELLO_AGENT_PROFILE"] = "test"
    # `.env` discovery: point it at a file we control (and never read real
    # user secrets even by accident).
    os.environ["HELLO_AGENT_DOTENV_PATH"] = str(tmp / ".env")
    # Disable auto-config of logging during tests; tests that need it call
    # setup_logging() themselves.
    os.environ.pop("HELLO_AGENT_SETUP_LOGGING", None)

    # Flush cached singletons that were built from the *previous* env.
    try:
        from hello_agent.core import config as _config_mod

        _config_mod.reload_config()
    except Exception:  # noqa: BLE001 — best-effort; tests will see defaults
        pass

    yield tmp

    # Cleanup: best-effort; tmp_path_factory handles the dir itself.
    os.environ.pop("HELLO_AGENT_HOME", None)
    os.environ.pop("HELLO_AGENT_PROFILE", None)
    os.environ.pop("HELLO_AGENT_DOTENV_PATH", None)


@pytest.fixture()
def tmp_hello_agent_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test isolated $HELLO_AGENT_HOME.

    Useful when a single test mutates the home (e.g. writes a config.yaml)
    and we want the next test to start fresh.
    """
    monkeypatch.setenv("HELLO_AGENT_HOME", str(tmp_path))
    # Flush config cache so the next get_config() re-reads from the new home.
    try:
        from hello_agent.core import config as _config_mod

        _config_mod.reload_config()
    except Exception:  # noqa: BLE001
        pass
    return tmp_path


@pytest.fixture()
def reset_singletons() -> None:
    """Flush all process-level singletons (config + env)."""
    try:
        from hello_agent.core import config as _config_mod

        _config_mod.reload_config()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture(scope="session")
def worktree_root() -> Path:
    """The repository root (where pyproject.toml lives)."""
    return Path(__file__).resolve().parent.parent
