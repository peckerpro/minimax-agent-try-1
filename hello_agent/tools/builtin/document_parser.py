"""document_parser — MinerU 2.5 Pro + markitdown + pypdf + raw fallback chain.

PDF:  MinerU → markitdown → pypdf
Office docs / html:  markitdown
Images:  MinerU (with OCR) → markitdown
Text / code:  raw read
Other:  markitdown → raw

If `markitdown` isn't installed, the chain silently falls through to the next
parser. If all parsers fail, returns a `ToolResponse.fail` with a hint of
the last error.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from hello_agent.core.config import get_env
from hello_agent.core.logging import get_logger
from hello_agent.core.types import ToolDefinition, ToolResponse, ToolResult
from hello_agent.tools.registry import ToolRegistry

logger = get_logger(__name__)


def _parse_with_mineru(path: Path) -> dict[str, Any]:
    env = get_env()
    if not env.mineru_api_key:
        raise RuntimeError("MINERU_API_KEY not set")
    headers = {"Authorization": f"Bearer {env.mineru_api_key}"}
    with path.open("rb") as f:
        upload_resp = httpx.post(
            f"{env.mineru_base_url}/file/upload",
            headers=headers,
            files={"file": (path.name, f, "application/octet-stream")},
            data={"model": env.mineru_model},
            timeout=60.0,
        )
    upload_resp.raise_for_status()
    task_id = upload_resp.json()["data"]["task_id"]
    for _ in range(60):  # 5 min max at 5s/poll
        poll = httpx.get(
            f"{env.mineru_base_url}/file/query/{task_id}",
            headers=headers,
            timeout=30.0,
        )
        poll.raise_for_status()
        data = poll.json().get("data", {})
        if data.get("state") == "success":
            text_url = data.get("full_md_link") or data.get("text_url")
            text = httpx.get(text_url, timeout=60.0).text if text_url else data.get("text", "")
            return {
                "text": text,
                "metadata": {"task_id": task_id, "model": env.mineru_model, **data.get("metadata", {})},
                "page_count": data.get("page_count"),
                "parser_used": "mineru",
            }
        if data.get("state") in ("failed", "error"):
            raise RuntimeError(f"MinerU failed: {data.get('err_msg', 'unknown')}")
        time.sleep(5)
    raise TimeoutError("MinerU poll timed out after 5 minutes")


def _parse_with_markitdown(path: Path) -> dict[str, Any]:
    from markitdown import MarkItDown  # type: ignore[import-not-found]

    md = MarkItDown()
    result = md.convert(str(path))
    return {
        "text": result.text_content,
        "metadata": {"source": str(path), "size_bytes": path.stat().st_size},
        "page_count": None,
        "parser_used": "markitdown",
    }


def _parse_with_pypdf(path: Path) -> dict[str, Any]:
    from pypdf import PdfReader  # type: ignore[import-not-found]

    reader = PdfReader(str(path))
    text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    return {
        "text": text,
        "metadata": {"source": str(path), "page_count": len(reader.pages)},
        "page_count": len(reader.pages),
        "parser_used": "pypdf",
    }


def _parse_raw(path: Path) -> dict[str, Any]:
    return {
        "text": path.read_text(encoding="utf-8", errors="replace"),
        "metadata": {"source": str(path), "size_bytes": path.stat().st_size},
        "page_count": None,
        "parser_used": "raw",
    }


_PDF = {".pdf"}
_BINARY_DOCS = {".docx", ".xlsx", ".pptx", ".html", ".htm"}
_TEXT = {".md", ".txt", ".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".csv"}
_IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}


def parse_document(path_str: str, force_parser: str = "") -> ToolResponse:
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        return ToolResponse.fail(f"File not found: {path}")
    if not path.is_file():
        return ToolResponse.fail(f"Not a file: {path}")
    suffix = path.suffix.lower()

    is_pdf = suffix in _PDF
    is_binary_doc = suffix in _BINARY_DOCS
    is_text = suffix in _TEXT
    is_image = suffix in _IMAGES

    # Build parser chain
    if force_parser == "mineru":
        chain: list[Callable[[Path], dict[str, Any]]] = [_parse_with_mineru]
    elif force_parser == "markitdown":
        chain = [_parse_with_markitdown]
    elif force_parser == "pypdf":
        chain = [_parse_with_pypdf]
    elif force_parser == "raw":
        chain = [_parse_raw]
    elif is_pdf:
        chain = [_parse_with_mineru, _parse_with_markitdown, _parse_with_pypdf]
    elif is_binary_doc:
        chain = [_parse_with_markitdown]
    elif is_text:
        chain = [_parse_raw]
    elif is_image:
        chain = [_parse_with_mineru, _parse_with_markitdown]
    else:
        chain = [_parse_with_markitdown, _parse_raw]

    errors: list[str] = []
    for parser in chain:
        try:
            return ToolResponse.ok(parser(path))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{parser.__name__}: {type(exc).__name__}: {exc}")
            logger.debug("parser {} failed: {}", parser.__name__, exc)
            continue

    return ToolResponse.fail("All parsers failed", hint="; ".join(errors))


def _to_result(response: ToolResponse, tool_call_id: str) -> ToolResult:
    content = (
        response.data
        if isinstance(response.data, str)
        else (response.to_json() if response.data is not None else "")
    )
    return ToolResult(
        tool_call_id=tool_call_id,
        content=content,
        is_error=not response.success,
        truncated=bool(response.hint and "truncated" in response.hint.lower()),
    )


def register(registry: ToolRegistry) -> None:
    registry.register(
        name="document_parser",
        toolset="knowledge",
        schema=ToolDefinition(
            name="document_parser",
            description=(
                "Parse a document file (PDF, DOCX, XLSX, MD, etc.) to text/markdown. "
                "Uses MinerU 2.5 Pro for PDFs by default; falls back to markitdown "
                "or pypdf if MinerU fails or is unavailable."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file."},
                    "force_parser": {
                        "type": "string",
                        "enum": ["", "mineru", "markitdown", "pypdf", "raw"],
                        "description": "Force a specific parser (bypasses fallback chain).",
                    },
                },
                "required": ["path"],
            },
        ),
        handler=lambda args, **kw: _to_result(
            parse_document(args.get("path", ""), args.get("force_parser", "")),
            kw.get("tool_call_id", ""),
        ),
    )
