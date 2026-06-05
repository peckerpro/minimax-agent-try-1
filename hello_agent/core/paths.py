"""Profile-aware home directory resolution.

Borrowed from `NousResearch/hermes-agent/hermes_constants.py` with these changes:
- Renamed `hermes_home` → `hello_agent_home`
- On Windows, default to `%LOCALAPPDATA%\\hello-agent\\` (system-wide install pattern)
- On other platforms, default to `~/.hello-agent/`
- Profile support: `HELLO_AGENT_PROFILE=coder` → `.../profiles/coder/`
- Explicit override: `HELLO_AGENT_HOME=/some/path`
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "hello-agent"  # dash, not underscore, for Windows-safe directory name
HOME_ENV_VAR = "HELLO_AGENT_HOME"
PROFILE_ENV_VAR = "HELLO_AGENT_PROFILE"
CONFIG_FILENAME = "config.yaml"


def _default_home() -> Path:
    """Return the platform-default home, ignoring env overrides.

    - Windows:  %LOCALAPPDATA%\\hello-agent (falls back to $HOME/.hello-agent)
    - else:     $HOME/.hello-agent
    """
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / APP_NAME
        # No LOCALAPPDATA (rare, e.g. some service accounts) — fall back to home.
        return Path.home() / f".{APP_NAME}"
    return Path.home() / f".{APP_NAME}"


def _apply_profile_override() -> None:
    """Apply HELLO_AGENT_PROFILE / HELLO_AGENT_HOME at import time.

    Sets HELLO_AGENT_HOME in the environment to the resolved final path so that
    child processes (uvicorn, tray) inherit the same home.

    Must run before any other hello_agent module reads HELLO_AGENT_HOME.
    Called automatically from hello_agent/__init__.py.
    """
    # If the user already set HELLO_AGENT_HOME explicitly, honor it verbatim.
    if HOME_ENV_VAR in os.environ and os.environ[HOME_ENV_VAR]:
        return

    profile = os.environ.get(PROFILE_ENV_VAR, "").strip()
    if profile and profile != "default":
        resolved = _default_home() / "profiles" / profile
    else:
        resolved = _default_home()
    os.environ[HOME_ENV_VAR] = str(resolved)


def get_hello_agent_home() -> Path:
    """Return the current profile's home directory.

    Resolution order:
    1. $HELLO_AGENT_HOME env var (explicit override, e.g. for tests)
    2. $HELLO_AGENT_PROFILE → ~/.hello-agent/profiles/<name>/ (if set & non-default)
    3. Platform default
    """
    explicit = os.environ.get(HOME_ENV_VAR, "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    # Fall back to profile/default resolution.
    profile = os.environ.get(PROFILE_ENV_VAR, "").strip()
    if profile and profile != "default":
        return (_default_home() / "profiles" / profile).resolve()
    return _default_home().resolve()


def display_hello_agent_home() -> str:
    """User-facing home display, abbreviating to ~/.hello-agent when possible.

    Used in log messages so the default profile reads naturally.
    """
    home = get_hello_agent_home()
    default = _default_home().resolve()
    try:
        rel = home.relative_to(default.parent)
        if str(rel).replace("\\", "/") == f".{APP_NAME}":
            return f"~/{rel}".replace("\\", "/")
    except ValueError:
        pass
    return str(home)


def ensure_home() -> Path:
    """get_hello_agent_home() + mkdir(parents=True, exist_ok=True). Returns the path."""
    home = get_hello_agent_home()
    home.mkdir(parents=True, exist_ok=True)
    return home
