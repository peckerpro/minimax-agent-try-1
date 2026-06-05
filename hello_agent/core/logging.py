"""Loguru setup.

Replaces `hermes_logging.py` (stdlib `logging`). v0.1 ships these sinks:
- console (rich-style color, optional)
- logs/agent.log (INFO+, 10MB rotation, 5 backups)
- logs/errors.log (WARNING+, 10MB rotation)
- logs/tools.log (filter: extra.category == "tool")
- logs/llm.log (filter: extra.category == "llm")
"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _loguru_logger

from hello_agent.core.paths import get_hello_agent_home

_CONFIGURED = False


def setup_logging(log_dir: Path | None = None, level: str | None = None) -> None:
    """Configure loguru sinks. Idempotent — calling twice is a no-op."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    # Late import to avoid a config -> logging cycle.
    try:
        from hello_agent.core.config import get_config

        cfg_logging = get_config().logging
    except Exception:
        # Config may not be loadable (e.g. fresh install) — fall back to defaults.
        cfg_logging = None

    effective_level = level or (cfg_logging.level if cfg_logging else "INFO")
    pretty = bool(cfg_logging.console_pretty) if cfg_logging else True

    if log_dir is None:
        log_dir = get_hello_agent_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Remove default sink
    _loguru_logger.remove()

    # Console
    if pretty:
        _loguru_logger.add(
            sys.stderr,
            level=effective_level,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
                "<level>{message}</level>"
            ),
        )
    else:
        _loguru_logger.add(sys.stderr, level=effective_level)

    # File sinks
    _loguru_logger.add(
        log_dir / "agent.log",
        level="INFO",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
    )
    _loguru_logger.add(
        log_dir / "errors.log",
        level="WARNING",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
    )
    _loguru_logger.add(
        log_dir / "tools.log",
        level="INFO",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        filter=lambda record: "tool" in record["extra"].get("category", ""),
    )
    _loguru_logger.add(
        log_dir / "llm.log",
        level="INFO",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        filter=lambda record: "llm" in record["extra"].get("category", ""),
    )

    _CONFIGURED = True


def get_logger(name: str):
    """Return a loguru logger bound to a module name. Usage: `log = get_logger(__name__)`."""
    return _loguru_logger.bind(module=name)


# Public re-export of the underlying loguru logger for advanced cases.
logger = _loguru_logger
