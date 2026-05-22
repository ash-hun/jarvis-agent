from __future__ import annotations

from typing import Any

import httpx

from jarvis.model_layer.types import TextContent, ToolResultMessage


class WebSearchTool:
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
    """DuckDuckGo Instant Answers API — 무료, 키 불필요."""
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
