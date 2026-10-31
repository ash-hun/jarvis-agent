"""tools 의 web_search: 키가 있으면 Brave, 없으면 DuckDuckGo 로 찾아 정리하고 실패를 오류로 알리는지 검증한다."""

import httpx
import pytest
from pydantic import SecretStr

from jarvis.core.tools.builtin.web_search import WebSearchTool, parse_ddg_html
from tests.fixtures.tools_helpers import route_httpx
from jarvis.jarvis_config import get_settings

_DDG_PAGE = """
<div class="result results_links result--ad"><a class="result__a" href="https://ad.example">광고</a></div>
<div class="result results_links web-result ">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a" href="https://blog.example/a">LLM <b>에이전트</b> 사례</a>
  </h2>
  <a class="result__snippet" href="https://blog.example/a">SK, LG 의 <b>도입</b> 성과 &amp; 인사이트</a>
</div>
<div class="result results_links web-result ">
  <h2 class="result__title">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.example%2Fb&amp;rut=x">둘째</a>
  </h2>
</div>
"""

FIRST = {"title": "LLM 에이전트 사례", "url": "https://blog.example/a", "snippet": "SK, LG 의 도입 성과 & 인사이트"}


def _ddg_results(n: int) -> str:
    return "".join(
        f'<div class="result web-result"><a class="result__a" href="https://e.example/{i}">T{i}</a></div>'
        for i in range(n)
    )


def _ddg(page: str, instant: dict | None = None):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(200, text=page)
        return httpx.Response(200, json=instant or {"Abstract": "", "RelatedTopics": []})

    return handler


def test_web_search_exposes_query_parameter():
    tool = WebSearchTool()

    assert (tool.name, tool.execution_mode) == ("web_search", "parallel")
    assert "query" in tool.parameters["properties"]


async def test_web_search_formats_ddg_results_without_a_key(monkeypatch):
    route_httpx(monkeypatch, _ddg(_DDG_PAGE))

    result = await WebSearchTool().execute("c1", {"query": "LLM 에이전트"})

    text = result.content[0].text
    assert result.is_error is False
    assert "Search results for:" in text
    assert "LLM 에이전트 사례" in text and "https://blog.example/a" in text and "도입 성과 & 인사이트" in text


async def test_web_search_respects_max_results(monkeypatch):
    route_httpx(monkeypatch, _ddg(_ddg_results(20)))

    result = await WebSearchTool().execute("c1", {"query": "test", "max_results": 3})

    assert result.is_error is False
    assert "3. T2" in result.content[0].text and "4." not in result.content[0].text


async def test_web_search_reports_no_results(monkeypatch):
    route_httpx(monkeypatch, _ddg("<html></html>"))

    result = await WebSearchTool().execute("c1", {"query": "test"})

    assert "No results found" in result.content[0].text


async def test_web_search_uses_brave_when_key_configured(monkeypatch):
    seen = route_httpx(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"web": {"results": [{"title": "Brave Result", "url": "https://brave.com", "description": "t"}]}}
        ),
    )
    monkeypatch.setattr(get_settings().web_search, "brave_api_key", SecretStr("test-key"))

    result = await WebSearchTool().execute("c1", {"query": "test query"})

    assert result.is_error is False
    assert "Brave Result" in result.content[0].text
    assert {r.url.host for r in seen} == {"api.search.brave.com"}


async def test_web_search_network_error_returns_error_result(monkeypatch):
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Network timeout")

    route_httpx(monkeypatch, fail)

    result = await WebSearchTool().execute("c1", {"query": "test"})

    assert result.is_error is True
    assert "Search failed" in result.content[0].text


@pytest.mark.parametrize(
    ("page", "limit", "expected"),
    [
        (_DDG_PAGE, 5, [FIRST, {"title": "둘째", "url": "https://docs.example/b", "snippet": ""}]),
        (_DDG_PAGE, 1, [FIRST]),
        ("<html></html>", 5, []),
    ],
)
def test_parse_ddg_html_skips_ads_and_unwraps_links(page, limit, expected):
    assert parse_ddg_html(page, limit) == expected
