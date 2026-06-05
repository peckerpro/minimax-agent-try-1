"""Tests for hello_agent.core.config."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_load_config_returns_default_when_no_yaml(
    tmp_hello_agent_home: Path, reset_singletons: None
) -> None:
    """With no config.yaml present, load_config() must return a fully-defaulted config."""
    from hello_agent.core.config import HelloAgentConfig, load_config

    cfg = load_config()
    assert isinstance(cfg, HelloAgentConfig)
    # Spot-check a handful of defaults from the spec.
    assert cfg.agent.default_type in {"simple", "react", "plan_solve", "reflection"}
    assert cfg.agent.max_iterations > 0
    assert cfg.context.max_context_tokens > 0
    assert cfg.logging.level == "INFO"


def test_load_config_uses_local_yaml(
    tmp_hello_agent_home: Path, reset_singletons: None
) -> None:
    """A config.yaml at $HELLO_AGENT_HOME must override defaults."""
    yaml_path = tmp_hello_agent_home / "config.yaml"
    yaml_path.write_text(
        "agent:\n"
        "  default_type: simple\n"
        "  max_iterations: 7\n"
        "logging:\n"
        "  level: DEBUG\n",
        encoding="utf-8",
    )

    from hello_agent.core.config import load_config

    cfg = load_config()
    assert cfg.agent.default_type == "simple"
    assert cfg.agent.max_iterations == 7
    assert cfg.logging.level == "DEBUG"


def test_load_config_rejects_non_mapping(
    tmp_hello_agent_home: Path, reset_singletons: None
) -> None:
    """A config.yaml that is not a YAML mapping must raise (don't silently fall back)."""
    yaml_path = tmp_hello_agent_home / "config.yaml"
    yaml_path.write_text("- just\n- a\n- list\n", encoding="utf-8")

    from hello_agent.core.config import load_config

    with pytest.raises(ValueError, match="must contain a YAML mapping"):
        load_config()


def test_get_config_is_singleton(tmp_hello_agent_home: Path, reset_singletons: None) -> None:
    """get_config() must cache the result and return the same instance."""
    from hello_agent.core import config as config_mod

    a = config_mod.get_config()
    b = config_mod.get_config()
    assert a is b


def test_reload_config_flushes_singleton(
    tmp_hello_agent_home: Path, reset_singletons: None
) -> None:
    """reload_config() must re-read from disk."""
    from hello_agent.core import config as config_mod

    config_mod.reload_config()  # first read
    config_mod.get_config()  # populate the cache

    # Mutate the on-disk config.
    (tmp_hello_agent_home / "config.yaml").write_text(
        "agent:\n  max_iterations: 42\n", encoding="utf-8"
    )

    # Without reload, the cache is stale.
    assert config_mod.get_config().agent.max_iterations != 42

    # After reload, we see the new value.
    second = config_mod.reload_config()
    assert second.agent.max_iterations == 42


def test_env_settings_loads_dotenv(
    tmp_hello_agent_home: Path,
    reset_singletons: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A .env file with LLM_BASE_URL must be picked up by EnvSettings."""
    env_path = tmp_hello_agent_home / ".env"
    env_path.write_text(
        "LLM_BASE_URL=https://example.invalid/v1\n"
        "LLM_API_KEY=test-key\n"
        "LLM_MODEL=test-model\n",
        encoding="utf-8",
    )
    # Point load_env() at this specific file. The session-level conftest
    # already set HELLO_AGENT_DOTENV_PATH; this per-test override makes
    # the assertion independent of the session home.
    monkeypatch.setenv("HELLO_AGENT_DOTENV_PATH", str(env_path))

    from hello_agent.core import config as config_mod

    env = config_mod.load_env()
    assert env.llm_base_url == "https://example.invalid/v1"
    assert env.llm_api_key == "test-key"
    assert env.llm_model == "test-model"
