"""Configuration loader.

Merges `config.yaml` (committed defaults) + `.env` (deployment overrides) +
in-memory overrides (CLI flags). See docs/ENGINEERING.md §4.3 for the full
default config shape.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from hello_agent.core.paths import CONFIG_FILENAME, get_hello_agent_home

# --- config.yaml sub-models -----------------------------------------------------


class AgentConfig(BaseModel):
    default_type: Literal["simple", "react", "plan_solve", "reflection"] = "react"
    max_iterations: int = 30
    max_cost_per_turn_usd: float = 0.50
    enable_memory_recall: bool = True
    enable_rag: bool = True
    memory_top_k: int = 5
    rag_top_k: int = 8


class TerminalConfig(BaseModel):
    cwd: Path | None = None
    shell_timeout_seconds: int = 60
    shell_max_output_bytes: int = 50_000


class MemoryConfig(BaseModel):
    short_term_max_messages: int = 50
    episodic_summarize_every_n_turns: int = 20
    obsidian_vault_path: Path | None = None
    obsidian_git_repo: str = "peckerpro/hello-agent-memory"
    obsidian_git_token: str | None = None
    obsidian_auto_commit_minutes: int = 5
    obsidian_auto_push_minutes: int = 15


class RagConfig(BaseModel):
    default_strategy: Literal["rewrite", "hyde", "multi_query", "rerank"] = "rewrite"
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    embedding_provider: Literal["openai", "local"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    chromadb_persist_dir: Path = Path("./data/chromadb")
    embedder_batch_size: int = 32


class ToolsConfig(BaseModel):
    enabled: list[str] = Field(
        default_factory=lambda: [
            "file_tools",
            "shell_tool",
            "web_search",
            "web_fetch",
            "document_parser",
            "todowrite",
            "notify",
        ]
    )
    disabled: list[str] = Field(default_factory=list)
    require_confirmation: list[str] = Field(
        default_factory=lambda: [
            "shell_tool.run_powershell",
            "shell_tool.run_cmd",
            "file_tools.write_file",
            "file_tools.edit_file",
        ]
    )


class ContextConfig(BaseModel):
    max_context_tokens: int = 128_000
    response_reserve_tokens: int = 4_000
    summarize_after_tokens: int = 100_000
    truncator_strategy: Literal["head_tail", "middle_out", "summarize"] = "head_tail"
    truncator_head_lines: int = 50
    truncator_tail_lines: int = 20


class LoggingConfig(BaseModel):
    level: str = "INFO"
    console_pretty: bool = True


class TracingConfig(BaseModel):
    enabled: bool = True
    export_json: bool = True
    export_dir: Path = Path("~/.hello-agent/traces").expanduser()


class HelloAgentConfig(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    terminal: TerminalConfig = Field(default_factory=TerminalConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)


# --- .env / env-var settings ----------------------------------------------------


class EnvSettings(BaseSettings):
    """Secrets + deployment overrides that come from .env or the OS environment."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_aux_model: str = "gpt-4o-mini"
    llm_vision_model: str = "gpt-4o"
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 3

    # MinerU
    mineru_api_key: str = ""
    mineru_base_url: str = "https://mineru.net/api/v4"
    mineru_model: str = "MinerU2.5Pro"

    # Web UI
    web_host: str = "127.0.0.1"
    web_port: int = 8648
    web_open_browser_on_start: bool = True

    # Obsidian (env-side; the config.yaml side lives in MemoryConfig)
    obsidian_vault_path: str = ""
    obsidian_git_repo: str = "peckerpro/hello-agent-memory"
    obsidian_git_token: str = ""


# --- Public API -----------------------------------------------------------------


def _resolve_config_path(config_path: Path | None) -> Path:
    if config_path is not None:
        return config_path.expanduser().resolve()
    return (get_hello_agent_home() / CONFIG_FILENAME).resolve()


def load_config(config_path: Path | None = None) -> HelloAgentConfig:
    """Load config.yaml (if present) and return a validated HelloAgentConfig.

    Order of precedence (lowest → highest):
      1. Built-in defaults in this file
      2. config.yaml at $HELLO_AGENT_HOME/config.yaml
      3. The `config_path` argument, if given
    """
    path = _resolve_config_path(config_path)
    data: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ValueError(
                f"Config file {path} must contain a YAML mapping, got {type(loaded).__name__}"
            )
        data = loaded

    # The .env OBSIDIAN_VAULT_PATH / OBSIDIAN_GIT_* are convenience overrides.
    env = load_env()
    if env.obsidian_vault_path and "memory" not in data:
        data["memory"] = {}
    if env.obsidian_vault_path:
        data.setdefault("memory", {})["obsidian_vault_path"] = env.obsidian_vault_path
    if env.obsidian_git_token:
        data.setdefault("memory", {})["obsidian_git_token"] = env.obsidian_git_token
    if env.obsidian_git_repo and "memory" not in data:
        data["memory"] = {"obsidian_git_repo": env.obsidian_git_repo}

    return HelloAgentConfig(**data)


def load_env() -> EnvSettings:
    """Load .env via pydantic-settings. Reads CWD/.env by default; set HELLO_AGENT_DOTENV_PATH to override."""
    dotenv_path = os.environ.get("HELLO_AGENT_DOTENV_PATH", ".env")
    if dotenv_path and Path(dotenv_path).exists():
        return EnvSettings(_env_file=dotenv_path, _env_file_encoding="utf-8")
    return EnvSettings(_env_file=None)


_config: HelloAgentConfig | None = None
_env: EnvSettings | None = None


def get_config() -> HelloAgentConfig:
    """Process-wide singleton config (lazy-loaded)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_env() -> EnvSettings:
    """Process-wide singleton env settings (lazy-loaded)."""
    global _env
    if _env is None:
        _env = load_env()
    return _env


def reload_config() -> HelloAgentConfig:
    """Force re-read of config.yaml + .env. Used by `hello-agent config reload`."""
    global _config, _env
    _config = None
    _env = None
    return get_config()
