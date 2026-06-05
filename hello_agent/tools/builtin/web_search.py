"""web_search — DuckDuckGo HTML (no key) + SearXNG fallback."""
from __future__ import annotations

from typing import Any

import httpx

from hello_agent.core.types import ToolDefinition, ToolResponse, ToolResult
from hello_agent.tools.registry import ToolRegistry


def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, str]]:
    url = "https://html.duckduckgo.com/html/"
    try:
        resp = httpx.post(url, data={"q": query, "kl": "us-en"}, timeout=20.0,
                          headers={"User-Agent": "hello-agent/0.1 (https://github.com/peckerpro/hello-agent-2)"})
        resp.raise_for_status()
    except Exception:  # noqa: BLE001
        return []
    # Naive HTML extraction — DDG's HTML interface is stable enough for a parser like selectolax
    try:
        from selectolax.parser import HTMLParser  # type: ignore[import-not-found]
    except ImportError:
        # Fall back to a very simple regex-based parse
        import re
        snippets: list[dict[str, str]] = []
        for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.S):
            href = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if href and title:
                snippets.append({"title": title, "url": href, "snippet": ""})
                if len(snippets) >= max_results:
                    break
        return snippets
    tree = HTMLParser(resp.text)
    out: list[dict[str, str]] = []
    for node in tree.css("div.result"):
        a = node.css_first("a.result__a")
        if a is None:
            continue
        href = a.attributes.get("href", "")
        title = a.text(strip=True)
        snippet_node = node.css_first("a.result__snippet")
        snippet = snippet_node.text(strip=True) if snippet_node else ""
        if href and title:
            out.append({"title": title, "url": href, "snippet": snippet})
        if len(out) >= max_results:
            break
    return out


def _search_searxng(query: str, max_results: int, instance: str = "https://searx.be") -> list[dict[str, str]]:
    try:
        resp = httpx.get(
            f"{instance}/search",
            params={"q": query, "format": "json", "categories": "general"},
            timeout=20.0,
            headers={"User-Agent": "hello-agent/0.1"},
        )
        resp.raise_for_status()
    except Exception:  # noqa: BLE001
        return []
    data = resp.json()
    out: list[dict[str, str]] = []
    for r in data.get("results", [])[:max_results]:
        out.append(
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
        )
    return out


def _search(args: dict[str, Any]) -> ToolResponse:
    query = args.get("query", "")
    if not query:
        return ToolResponse.fail("query is required")
    max_results = int(args.get("max_results", 5))
    # Try SearXNG first, fall back to DDG.
    results = _search_searxng(query, max_results)
    backend = "searxng" if results else "duckduckgo"
    if not results:
        results = _search_duckduckgo(query, max_results)
    if not results:
        return ToolResponse.fail("All search backends failed")
    return ToolResponse.ok({"results": results, "backend": backend})


def _to_result(response: ToolResponse, tool_call_id: str) -> ToolResult:
    content = (
        response.data
        if isinstance(response.data, str)
        else (response.to_json() if response.data is not None else "")
    )
    return ToolResult(tool_call_id=tool_call_id, content=content, is_error=not response.success)


def register(registry: ToolRegistry) -> None:
    registry.register(
        name="search",
        toolset="web_search",
        schema=ToolDefinition(
            name="search",
            description="Search the web and return a list of {title, url, snippet}.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "description": "Default 5."},
                },
                "required": ["query"],
            },
        ),
        handler=lambda args, **kw: _to_result(_search(args), kw.get("tool_call_id", "")),
    )
