"""RAG document loader (ENGINEERING.md §7.2.1).

Dispatches a file to the appropriate text-extraction path based on its
extension:

  - Text-native (md, txt, py, json, yaml, csv, …): read directly.
  - Office / pdf / image: delegate to `document_parser.parse_document`,
    which runs the MinerU → markitdown → pypdf fallback chain.

The supported-extension set is configurable via `rag.loader.extensions` in
config.yaml; we merge those defaults with the built-in set so users can
opt in to additional file types without a code change.

Returns a `dict` with keys:
  - `text`       — the extracted text body (str, may be empty)
  - `source`     — absolute path of the file (str)
  - `loader`     — name of the loader used (e.g. "text" or "document_parser.mineru")
  - `metadata`   — per-loader metadata (size, page_count, etc.)
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hello_agent.core.config import get_config
from hello_agent.core.logging import get_logger
from hello_agent.core.types import ToolResponse

logger = get_logger(__name__)


# Built-in defaults: same set as the Day-2 document_parser supports.
# These get merged with `config.rag.loader.extensions` at construction time.
_DEFAULT_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".rb",
        ".php",
        ".sh",
        ".bash",
        ".ps1",
        ".sql",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".xml",
        ".ini",
        ".env",
    }
)

# Extensions that need the document_parser chain (binary, office, image).
_PARSER_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".html",
        ".htm",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".tiff",
    }
)

# 50 MB hard limit per file — matches the spec. Larger files should be
# chunked / sharded before indexing.
_MAX_FILE_BYTES = 50_000_000


def _merged_extensions() -> frozenset[str]:
    """Combine built-in defaults with `config.rag.loader.extensions`."""
    cfg_exts: Iterable[str] = get_config().rag.loader.extensions or []
    # Normalize: lowercase, dot-prefixed.
    cfg_set = {
        e if e.startswith(".") else f".{e}" for e in cfg_exts
    }
    return _DEFAULT_TEXT_EXTENSIONS | _PARSER_EXTENSIONS | frozenset(cfg_set)


def load_file(path: str | Path) -> dict[str, Any]:
    """Load a single file. Returns a dict (or raises).

    Returned dict:
      {
        "text":     str,     # may be empty
        "source":   str,     # absolute path
        "loader":   str,     # "text" | "document_parser.<engine>"
        "metadata": dict,    # size, extension, parser_used, etc.
      }
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if not p.is_file():
        raise IsADirectoryError(f"Not a file: {p}")
    if p.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError(
            f"File too large: {p.stat().st_size} bytes (limit {_MAX_FILE_BYTES})"
        )

    suffix = p.suffix.lower()
    if suffix in _DEFAULT_TEXT_EXTENSIONS or suffix in {e.lower() for e in get_config().rag.loader.extensions}:
        return _load_text(p, suffix)
    if suffix in _PARSER_EXTENSIONS:
        return _load_via_parser(p)
    # Unknown extension — try parser chain first (it can sometimes handle
    # arbitrary text-ish formats), then fall back to raw read.
    result = _load_via_parser(p)
    if result.get("text"):
        return result
    return _load_text(p, suffix)


def load_files(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Load a batch of files. Errors per-file are logged and skipped."""
    out: list[dict[str, Any]] = []
    for p in paths:
        try:
            out.append(load_file(p))
        except Exception as exc:  # noqa: BLE001
            logger.bind(category="rag").warning(
                "load_file failed for {}: {}", p, exc
            )
            continue
    return out


def load_directory(
    path: str | Path,
    *,
    recursive: bool = True,
    extensions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Walk a directory, load all files with allowed extensions.

    Args:
        path:       The directory to walk.
        recursive:  If True, descend into subdirectories.
        extensions: Override the allowed extension set. If None, uses
                    `_merged_extensions()`. Pass an empty list to mean
                    "all files" (still subject to the size cap).

    Skips files that fail to load (with a warning). Empty directories
    return an empty list.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Directory not found: {p}")
    if not p.is_dir():
        raise NotADirectoryError(f"Not a directory: {p}")

    if extensions is None:
        allowed: set[str] = set(_merged_extensions())
    else:
        allowed = {e if e.startswith(".") else f".{e}" for e in extensions}
        allowed = {e.lower() for e in allowed}

    # If the caller passed an empty list, treat it as "no filter".
    if extensions is not None and not extensions:
        allowed = set()

    candidates: list[Path] = []
    if recursive:
        for child in p.rglob("*"):
            if child.is_file() and (not allowed or child.suffix.lower() in allowed):
                candidates.append(child)
    else:
        for child in p.iterdir():
            if child.is_file() and (not allowed or child.suffix.lower() in allowed):
                candidates.append(child)
    candidates.sort()

    logger.bind(category="rag").info(
        "load_directory: {} (recursive={}, exts={}) → {} candidate files",
        p,
        recursive,
        sorted(allowed) if allowed else "(all)",
        len(candidates),
    )
    return load_files(candidates)


# ─── Internals ---------------------------------------------------------------


def _load_text(p: Path, suffix: str) -> dict[str, Any]:
    """Read a text-native file directly. Always UTF-8 with replacement."""
    text = p.read_text(encoding="utf-8", errors="replace")
    return {
        "text": text,
        "source": str(p),
        "loader": "text",
        "metadata": {
            "size_bytes": p.stat().st_size,
            "extension": suffix,
        },
    }


def _load_via_parser(p: Path) -> dict[str, Any]:
    """Dispatch through the document_parser chain.

    We tolerate a non-success ToolResponse by returning an empty-text
    record — the indexer will skip it but won't crash.
    """
    from hello_agent.tools.builtin.document_parser import parse_document

    resp: ToolResponse = parse_document(str(p))
    if not resp.success or not isinstance(resp.data, dict):
        return {
            "text": "",
            "source": str(p),
            "loader": "document_parser.failed",
            "metadata": {
                "size_bytes": p.stat().st_size,
                "error": (resp.error if resp else "unknown"),
            },
        }
    data = resp.data
    parser_used = data.get("parser_used", "unknown")
    return {
        "text": str(data.get("text", "")),
        "source": str(p),
        "loader": f"document_parser.{parser_used}",
        "metadata": {
            "size_bytes": p.stat().st_size,
            "parser_used": parser_used,
            "page_count": data.get("page_count"),
            "extension": p.suffix.lower(),
            **(data.get("metadata") or {}),
        },
    }


def supported_extensions() -> list[str]:
    """Return the sorted list of file extensions this loader will accept."""
    return sorted(_merged_extensions())
