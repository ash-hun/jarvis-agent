"""tools 의 web_fetch 내장 도구: HTML 을 글로 바꿔 돌려주고 http(s) 가 아닌 주소는 거절하는지 검증한다."""

import httpx

from jarvis.core.tools.builtin.web_fetch import WebFetchTool
from tests.fixtures.tools_helpers import route_httpx

PAGE = "<html><head><style>x{}</style></head><body><h1>Hi</h1><p>World &amp; more</p></body></html>"


async def test_web_fetch_returns_page_text_without_tags_or_styles(monkeypatch):
    route_httpx(monkeypatch, lambda request: httpx.Response(200, html=PAGE))

    result = await WebFetchTool().execute("c1", {"url": "https://example.com"})

    text = result.content[0].text
    assert result.is_error is False
    assert "Hi" in text and "World & more" in text
    assert "<" not in text and "x{}" not in text


async def test_web_fetch_rejects_non_http_url():
    result = await WebFetchTool().execute("c1", {"url": "ftp://example.com"})

    assert result.is_error is True
    assert "Invalid URL" in result.content[0].text
