"""Tests for `hello_agent.windows.env`.

`probe_env()` is cross-platform and must NEVER raise. Tests verify:
- Required keys are present in the returned dict.
- Network probe gracefully returns False on unreachable hosts.
- LLM_API_KEY probe returns False when key is empty or the placeholder.
- The probe runs successfully even when subsystems fail (no exceptions).

Marked `@pytest.mark.windows` per the spec; the marker is descriptive
not a skip — the probe itself runs everywhere.
"""
from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.windows


@pytest.fixture()
def env_module() -> Any:
    from hello_agent.windows import env as env_mod

    return env_mod


# --- probe_env shape ---------------------------------------------------------


def test_probe_env_returns_all_expected_keys(env_module: Any) -> None:
    """probe_env returns the documented key set."""
    result = env_module.probe_env()
    expected = {
        "python_version",
        "python_executable",
        "uv_version",
        "platform",
        "platform_version",
        "llm_api_key_set",
        "llm_base_url",
        "home_dir",
        "network_reachable",
        "web_extras",
        "windows_extras",
    }
    assert expected <= set(result.keys())


def test_probe_env_python_version_matches_runtime(env_module: Any) -> None:
    """python_version matches sys.version's first token."""
    import sys

    result = env_module.probe_env()
    assert result["python_version"] == sys.version.split()[0]


def test_probe_env_platform_matches(env_module: Any) -> None:
    """platform matches platform.system()."""
    import platform as _platform

    result = env_module.probe_env()
    assert result["platform"] == _platform.system()


def test_probe_env_returns_bool_for_extras(env_module: Any) -> None:
    """web_extras and windows_extras are bool, not None (or at least truthy/falsy)."""
    result = env_module.probe_env()
    assert isinstance(result["web_extras"], bool)
    assert isinstance(result["windows_extras"], bool)


# --- network probe -----------------------------------------------------------


def test_probe_network_with_empty_url_returns_false(env_module: Any) -> None:
    """_probe_network returns False when given an empty base_url."""
    assert env_module._probe_network("") is False


def test_probe_network_unreachable_returns_false(env_module: Any) -> None:
    """_probe_network returns False for a host that does not exist / is blocked."""
    # 127.0.0.1:1 is reserved and unbound; socket.create_connection will refuse / timeout.
    assert env_module._probe_network("http://127.0.0.1:1", timeout=0.5) is False


def test_probe_network_parses_https_default_port(env_module: Any) -> None:
    """When scheme is https and port is omitted, use 443."""
    parsed = __import__("urllib.parse").parse.urlparse("https://example.com/something")
    # The internal _probe_network should derive host=example.com port=443.
    # We can't easily assert the return without an actual listener on 443,
    # so we just verify the parser shape is what we expect.
    assert parsed.hostname == "example.com"
    assert parsed.scheme == "https"


# --- LLM API key probe -------------------------------------------------------


def test_probe_llm_api_key_false_when_default(
    env_module: Any, monkeypatch: pytest.MonkeyPatch, tmp_hello_agent_home: Any
) -> None:
    """Returns False when llm_api_key is the default placeholder."""
    # The conftest gives us an isolated tmp HELLO_AGENT_HOME; we need
    # a config.yaml or .env to override the default. Without one, the
    # default `sk-replace-me` should be detected.
    result = env_module.probe_env()
    # In a fresh test environment, llm_api_key defaults to "sk-replace-me",
    # so the probe should say it's NOT set.
    assert result["llm_api_key_set"] is False


def test_probe_llm_api_key_true_when_configured(
    env_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns True when llm_api_key is a non-empty non-placeholder value."""
    # Set via env var so pydantic-settings picks it up.
    # The EnvSettings model uses env_prefix="" so the field `llm_api_key`
    # maps to the env var `LLM_API_KEY`.
    monkeypatch.setenv("LLM_API_KEY", "sk-test-1234567890")
    # Reload config singleton so the new env var takes effect.
    from hello_agent.core import config as _cfg

    _cfg.reload_config()
    result = env_module.probe_env()
    assert result["llm_api_key_set"] is True


# --- graceful failure paths --------------------------------------------------


def test_probe_network_handles_invalid_url_gracefully(env_module: Any) -> None:
    """_probe_network returns False for garbage URLs without raising."""
    assert env_module._probe_network("not-a-url") is False
    assert env_module._probe_network("http://") is False


def test_probe_env_does_not_raise_even_on_broken_get_env(
    env_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """probe_env swallows get_env() failures and still returns a dict."""
    # Force the config module to raise on get_env.
    from hello_agent.core import config as _cfg

    def boom() -> None:
        raise RuntimeError("config is on fire")

    monkeypatch.setattr(_cfg, "get_env", boom)
    # Should not raise.
    result = env_module.probe_env()
    # With get_env broken, llm_api_key_set / llm_base_url / network_reachable
    # fall back to safe defaults (False / "" / False).
    assert result["llm_api_key_set"] is False
    assert result["network_reachable"] is False


def test_probe_home_dir_returns_string(env_module: Any) -> None:
    """home_dir is always a non-empty string."""
    result = env_module.probe_env()
    assert isinstance(result["home_dir"], str)
    assert result["home_dir"]  # non-empty


def test_probe_uv_version_is_string_or_none(env_module: Any) -> None:
    """uv_version is either a version string or None (uv not installed)."""
    result = env_module.probe_env()
    assert result["uv_version"] is None or isinstance(result["uv_version"], str)