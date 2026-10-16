"""[core] Brave Search(키 없으면 DuckDuckGo)로 웹을 검색하는 web_search 내장 도구."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from jarvis.core.tools.registry import JarvisTool
from jarvis.model_layer.types import TextContent, ToolResultMessage

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
# 기본 httpx UA 는 차단될 수 있어 브라우저처럼 보이는 값을 쓴다
DDG_USER_AGENT = "Mozilla/5.0 (compatible; jarvis-agent)"
_DDG_TITLE = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
_DDG_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


class WebSearchTool(JarvisTool):
    name = "web_search"
    description = (
        "Search the web for current information. "
        "Use when you need up-to-date facts, news, or data not in your training knowledge."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    }
    execution_mode = "parallel"

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None) -> ToolResultMessage:
        query = params["query"]
        max_results = int(params.get("max_results", 5))

        try:
            results = await _search(query, max_results)
            text = _format_results(query, results)
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=text)],
            )
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"Search failed: {exc}")],
                is_error=True,
            )


async def _search(query: str, max_results: int) -> list[dict[str, str]]:
    """Brave Search API 우선, 키 없으면 DuckDuckGo fallback."""
    from jarvis.config import get_settings

    settings = get_settings()
    if settings.web_search.brave_api_key:
        return await _search_brave(
            query, max_results, settings.web_search.brave_api_key.get_secret_value()
        )
    return await _search_ddg(query, max_results)


async def _search_brave(query: str, max_results: int, api_key: str) -> list[dict[str, str]]:
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params: dict[str, Any] = {"q": query, "count": min(max_results, 20)}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

    results: list[dict[str, str]] = []
    for item in data.get("web", {}).get("results", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
        })
    return results


async def _search_ddg(query: str, max_results: int) -> list[dict[str, str]]:
    """DuckDuckGo HTML 검색 결과. 비면 Instant Answers 로 한 번 더. 무료, 키 불필요."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(DDG_HTML_URL, data={"q": query}, headers={"User-Agent": DDG_USER_AGENT})
        response.raise_for_status()
    results = parse_ddg_html(response.text, max_results)
    return results or await _search_ddg_instant(query, max_results)


def parse_ddg_html(page: str, max_results: int) -> list[dict[str, str]]:
    """html.duckduckgo.com 결과 페이지에서 제목, 링크, 요약을 꺼낸다. 광고 블록은 건너뛴다."""
    results: list[dict[str, str]] = []
    for block in page.split('class="result ')[1:]:
        if "result--ad" in block[:200]:
            continue
        title = _DDG_TITLE.search(block)
        if title is None:
            continue
        snippet = _DDG_SNIPPET.search(block)
        results.append({
            "title": _clean(title.group(2)),
            "url": _unwrap_ddg_link(html.unescape(title.group(1))),
            "snippet": _clean(snippet.group(1)) if snippet else "",
        })
        if len(results) >= max_results:
            break
    return results


def _clean(fragment: str) -> str:
    return html.unescape(_TAG.sub("", fragment)).strip()


def _unwrap_ddg_link(href: str) -> str:
    """//duckduckgo.com/l/?uddg=<실제 주소> 형태면 실제 주소를 꺼낸다."""
    if "uddg=" not in href:
        return href
    target = parse_qs(urlparse(href).query).get("uddg")
    return target[0] if target else href


async def _search_ddg_instant(query: str, max_results: int) -> list[dict[str, str]]:
    """DuckDuckGo Instant Answers API. 백과사전식 요약만 준다."""
    url = "https://api.duckduckgo.com/"
    params: dict[str, Any] = {
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
        "t": "jarvis",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    results: list[dict[str, str]] = []
    if data.get("Abstract"):
        results.append({
            "title": data.get("Heading", query),
            "url": data.get("AbstractURL", ""),
            "snippet": data["Abstract"],
        })

    for topic in data.get("RelatedTopics", []):
        if len(results) >= max_results:
            break
        if isinstance(topic, dict) and topic.get("Text"):
            results.append({
                "title": topic.get("Text", "")[:100],
                "url": topic.get("FirstURL", ""),
                "snippet": topic.get("Text", ""),
            })

    return results[:max_results]


def _format_results(query: str, results: list[dict[str, str]]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        if r["url"]:
            lines.append(f"   URL: {r['url']}")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
        lines.append("")
    return "\n".join(lines).strip()
