"""web_fetch — fetch a URL and return its content as readable text/markdown."""
from __future__ import annotations

import re
from typing import Any

import httpx

from hello_agent.core.types import ToolDefinition, ToolResponse, ToolResult
from hello_agent.tools.registry import ToolRegistry


def _html_to_text(html: str, max_bytes: int) -> str:
    """Best-effort HTML → plain text. Uses selectolax if available, else regex."""
    truncated_html = html.encode("utf-8", errors="replace")[:max_bytes].decode("utf-8", errors="replace")
    try:
        from selectolax.parser import HTMLParser  # type: ignore[import-not-found]
        tree = HTMLParser(truncated_html)
        # Drop script/style
        for tag in tree.css("script, style, noscript"):
            tag.decompose()
        text = tree.body.text(separator="\n") if tree.body else tree.text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except ImportError:
        # Fallback: strip tags crudely
        text = re.sub(r"<script[^>]*>.*?</script>", "", truncated_html, flags=re.S | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"\s+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()


def _fetch(args: dict[str, Any]) -> ToolResponse:
    url = args.get("url", "")
    if not url:
        return ToolResponse.fail("url is required")
    max_bytes = int(args.get("max_bytes", 1_000_000))
    timeout = float(args.get("timeout_seconds", 30.0))
    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "hello-agent/0.1 (https://github.com/peckerpro/hello-agent-2)"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return ToolResponse.fail(f"HTTP error: {exc}")
    ctype = resp.headers.get("content-type", "")
    if "html" in ctype.lower():
        text = _html_to_text(resp.text, max_bytes)
    else:
        text = resp.text[:max_bytes]
    truncated = len(resp.content) > max_bytes
    return ToolResponse.ok(
        {"text": text, "url": url, "content_type": ctype, "truncated": truncated, "size_bytes": len(resp.content)}
    )


def _to_result(response: ToolResponse, tool_call_id: str) -> ToolResult:
    content = (
        response.data
        if isinstance(response.data, str)
        else (response.to_json() if response.data is not None else "")
    )
    return ToolResult(tool_call_id=tool_call_id, content=content, is_error=not response.success)


def register(registry: ToolRegistry) -> None:
    registry.register(
        name="fetch",
        toolset="web_fetch",
        schema=ToolDefinition(
            name="fetch",
            description="Fetch a URL and return readable text/markdown.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_bytes": {"type": "integer"},
                    "timeout_seconds": {"type": "number"},
                },
                "required": ["url"],
            },
        ),
        handler=lambda args, **kw: _to_result(_fetch(args), kw.get("tool_call_id", "")),
    )
