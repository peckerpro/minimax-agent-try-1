"""Config route — get / put `config.yaml`.

`GET /api/config/` returns the current `HelloAgentConfig` as a JSON
dict (Pydantic's `model_dump(mode="json")`).

`PUT /api/config/` accepts a *partial* JSON body and merges it into
the in-memory config singleton, then writes the full merged config
back to `config.yaml`. The merge is shallow at the top level (e.g.
`{"agent": {"max_iterations": 25}}` replaces the whole `agent`
sub-block) so callers can update one section without losing the rest.

`POST /api/config/reload` discards the in-memory singleton and
re-reads from disk. Useful after the user edits `config.yaml` by hand.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from hello_agent.core.config import (
    HelloAgentConfig,
    get_config,
    get_hello_agent_home,
    reload_config,
)
from hello_agent.core.logging import get_logger
from hello_agent.core.paths import CONFIG_FILENAME

logger = get_logger(__name__)

router = APIRouter()


# ----- response models --------------------------------------------------------


class ConfigResponse(BaseModel):
    """The current config, plus a small set of useful metadata fields."""

    path: str
    data: dict[str, Any]


class UpdateResponse(BaseModel):
    updated: bool
    path: str
    data: dict[str, Any]


class ReloadResponse(BaseModel):
    reloaded: bool
    data: dict[str, Any]


# ----- helpers ----------------------------------------------------------------


def _config_path() -> Path:
    """`$HELLO_AGENT_HOME/config.yaml`. May not exist yet — that's fine."""
    return get_hello_agent_home() / CONFIG_FILENAME


def _to_jsonable(cfg: HelloAgentConfig) -> dict[str, Any]:
    """Pydantic -> JSON-safe dict (paths become strings, enums become values)."""
    return cfg.model_dump(mode="json")


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomic-ish YAML write: write to a tmp file then rename.

    `path` is created with parents if missing. We do NOT use a
    file lock — concurrent writers can stomp each other, but the
    Web UI is single-user so that's a non-issue for v0.2.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    # `os.replace` is atomic on Windows and POSIX.
    os.replace(tmp, path)


# ----- routes -----------------------------------------------------------------


@router.get("/", response_model=ConfigResponse)
async def get_config_endpoint() -> ConfigResponse:
    """Return the current config + the path it was loaded from."""
    cfg = get_config()
    return ConfigResponse(path=str(_config_path()), data=_to_jsonable(cfg))


@router.put("/", response_model=UpdateResponse)
async def update_config(payload: dict[str, Any]) -> UpdateResponse:
    """Merge `payload` into the in-memory config and write back to disk.

    The merge is shallow at the top level: each key in `payload`
    replaces the corresponding sub-block in the existing config.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")

    cfg = get_config()
    current = _to_jsonable(cfg)
    merged: dict[str, Any] = dict(current)
    for k, v in payload.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            # Shallow-merge one level down so the caller can update a
            # single field inside `agent` without losing the rest.
            sub = dict(merged[k])
            sub.update(v)
            merged[k] = sub
        else:
            merged[k] = v

    # Validate the merged shape. Pydantic errors become 400s so the UI
    # can show the validator's message.
    try:
        new_cfg = HelloAgentConfig(**merged)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "validation failed", "errors": exc.errors()},
        ) from exc

    # Persist the *normalized* shape (so file doesn't accumulate typos
    # / extra keys). Reuse the path the loader would have used.
    path = _config_path()
    _write_yaml(path, _to_jsonable(new_cfg))

    # Flush the in-memory singleton so the next `get_config()` reads
    # the freshly-written file.
    reload_config()
    logger.info("config updated at {}", path)
    return UpdateResponse(updated=True, path=str(path), data=_to_jsonable(get_config()))


@router.post("/reload", response_model=ReloadResponse)
async def reload() -> ReloadResponse:
    """Re-read `config.yaml` + `.env` from disk; drop the cached singleton."""
    cfg = reload_config()
    return ReloadResponse(reloaded=True, data=_to_jsonable(cfg))


__all__ = ["router", "ConfigResponse", "UpdateResponse", "ReloadResponse"]
