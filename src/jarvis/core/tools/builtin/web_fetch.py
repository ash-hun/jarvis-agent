from __future__ import annotations

import html
import re
from typing import Any

import httpx

from jarvis.model_layer.types import TextContent, ToolResultMessage

TOOL_NAME = "web_fetch"
TOOL_DESCRIPTION = (
    "Fetch a URL and return its content as readable text (HTML stripped). "
    "Use this to read a specific web page when you already have its URL — "
    "complements web_search, which only returns result snippets."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The URL to fetch (http or https)",
        },
        "max_length": {
            "type": "integer",
            "description": "Maximum characters of text to return (default: 10000)",
        },
    },
    "required": ["url"],
}

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n\s*\n\s*\n+")


class WebFetchTool:
    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "parallel"

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
    ) -> ToolResultMessage:
        url = params["url"]
        max_length = int(params.get("max_length", 10000))

        if not url.startswith(("http://", "https://")):
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"Invalid URL (must start with http/https): {url}")],
                is_error=True,
            )

        try:
            async with httpx.AsyncClient(
                timeout=15.0, follow_redirects=True, headers={"User-Agent": "jarvis/1.0"}
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"Fetch failed: {exc}")],
                is_error=True,
            )

        content_type = response.headers.get("content-type", "")
        text = _html_to_text(response.text) if "html" in content_type else response.text

        truncated = ""
        if len(text) > max_length:
            text = text[:max_length]
            truncated = f"\n\n[truncated to {max_length} chars]"

        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=[TextContent(text=f"Content of {url}:\n\n{text}{truncated}")],
        )


def _html_to_text(raw: str) -> str:
    """의존성 없이 HTML 태그를 제거하고 텍스트만 추출."""
    no_scripts = _SCRIPT_STYLE_RE.sub(" ", raw)
    no_tags = _TAG_RE.sub(" ", no_scripts)
    unescaped = html.unescape(no_tags)
    lines = [line.strip() for line in unescaped.splitlines()]
    collapsed = "\n".join(line for line in lines if line)
    return _WS_RE.sub("\n\n", collapsed).strip()
