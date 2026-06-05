"""Tests for hello_agent.core.paths."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_get_hello_agent_home_explicit_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HELLO_AGENT_HOME wins over the profile-derived default."""
    monkeypatch.setenv("HELLO_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("HELLO_AGENT_PROFILE", raising=False)

    from hello_agent.core import paths

    assert paths.get_hello_agent_home() == tmp_path.resolve()


def test_get_hello_agent_home_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HELLO_AGENT_PROFILE=coder -> .../profiles/coder/ under the default home."""
    # We don't actually want to write to the real default home. So we set
    # a temporary LOCALAPPDATA-equivalent by monkey-patching Path.home.
    monkeypatch.delenv("HELLO_AGENT_HOME", raising=False)
    monkeypatch.setenv("HELLO_AGENT_PROFILE", "coder")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    from hello_agent.core import paths

    expected = (tmp_path / paths.APP_NAME / "profiles" / "coder").resolve()
    assert paths.get_hello_agent_home() == expected


def test_get_hello_agent_home_default_profile_uses_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HELLO_AGENT_PROFILE=default (or unset) lands at the root home, not a 'default' sub-dir."""
    monkeypatch.delenv("HELLO_AGENT_HOME", raising=False)
    monkeypatch.delenv("HELLO_AGENT_PROFILE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    from hello_agent.core import paths

    expected = (tmp_path / paths.APP_NAME).resolve()
    assert paths.get_hello_agent_home() == expected


def test_ensure_home_creates_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ensure_home() must create the home if it doesn't exist (idempotent)."""
    target = tmp_path / "fresh_home"
    assert not target.exists()

    monkeypatch.setenv("HELLO_AGENT_HOME", str(target))
    monkeypatch.delenv("HELLO_AGENT_PROFILE", raising=False)

    from hello_agent.core import paths

    home = paths.ensure_home()
    assert home == target.resolve()
    assert target.is_dir()

    # Idempotent: a second call doesn't raise.
    paths.ensure_home()


def test_apply_profile_override_sets_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_apply_profile_override() must populate HELLO_AGENT_HOME for child processes."""
    monkeypatch.delenv("HELLO_AGENT_HOME", raising=False)
    monkeypatch.setenv("HELLO_AGENT_PROFILE", "writer")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    from hello_agent.core import paths

    paths._apply_profile_override()

    # After the override, HELLO_AGENT_HOME must point at profiles/writer/.
    assert os.environ.get(paths.HOME_ENV_VAR, "").endswith(os.path.join("profiles", "writer"))


def test_apply_profile_override_honors_explicit_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If HELLO_AGENT_HOME is set, profile-based derivation must NOT overwrite it."""
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("HELLO_AGENT_HOME", str(explicit))
    monkeypatch.setenv("HELLO_AGENT_PROFILE", "ignored")

    from hello_agent.core import paths

    paths._apply_profile_override()

    # Explicit home wins.
    assert os.environ[paths.HOME_ENV_VAR] == str(explicit)
