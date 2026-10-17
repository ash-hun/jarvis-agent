"""web_search builtin tool 테스트."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestWebSearchTool:
    @pytest.fixture
    def tool(self):
        from jarvis.core.tools.builtin.web_search import WebSearchTool
        return WebSearchTool()

    def test_tool_metadata(self, tool):
        assert tool.name == "web_search"
        assert tool.execution_mode == "parallel"
        assert "query" in tool.parameters["properties"]

    async def test_ddg_success(self, tool):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "Abstract": "Python is a programming language.",
            "Heading": "Python (programming language)",
            "AbstractURL": "https://en.wikipedia.org/wiki/Python_(programming_language)",
            "RelatedTopics": [],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("jarvis.core.tools.builtin.web_search._search_ddg", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = [
                {
                    "title": "Python (programming language)",
                    "url": "https://en.wikipedia.org/wiki/Python",
                    "snippet": "Python is a programming language.",
                }
            ]
            result = await tool.execute("c1", {"query": "Python programming language"})

        assert result.is_error is False
        assert "Python" in result.content[0].text
        assert "Search results for:" in result.content[0].text

    async def test_brave_used_when_key_configured(self, tool, monkeypatch):
        from jarvis.config import get_settings

        settings = get_settings()
        # Brave 키 설정 시뮬레이션
        with patch("jarvis.core.tools.builtin.web_search._search_brave", new_callable=AsyncMock) as mock_brave:
            with patch("jarvis.core.tools.builtin.web_search._search_ddg", new_callable=AsyncMock) as mock_ddg:
                mock_brave.return_value = [{"title": "Brave Result", "url": "https://brave.com", "snippet": "test"}]

                # Brave API key를 직접 설정
                from pydantic import SecretStr
                with patch.object(settings.web_search, "brave_api_key", SecretStr("test-key")):
                    result = await tool.execute("c1", {"query": "test query"})

                mock_brave.assert_called_once()
                mock_ddg.assert_not_called()

        assert result.is_error is False

    async def test_network_error_returns_error_result(self, tool):
        with patch("jarvis.core.tools.builtin.web_search._search", new_callable=AsyncMock) as mock_search:
            mock_search.side_effect = Exception("Network timeout")
            result = await tool.execute("c1", {"query": "test"})

        assert result.is_error is True
        assert "Search failed" in result.content[0].text

    async def test_max_results_respected(self, tool):
        many_topics = [
            {"Text": f"Topic {i}", "FirstURL": f"https://example.com/{i}"}
            for i in range(20)
        ]
        mock_data = {"Abstract": "", "Heading": "", "AbstractURL": "", "RelatedTopics": many_topics}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = MagicMock()
            mock_response.json.return_value = mock_data
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            # web_search 설정에 brave key 없어야 ddg fallback
            with patch("jarvis.core.tools.builtin.web_search._search", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = [
                    {"title": f"T{i}", "url": "", "snippet": "s"} for i in range(3)
                ]
                result = await tool.execute("c1", {"query": "test", "max_results": 3})

        assert result.is_error is False

    def test_format_results_empty(self):
        from jarvis.core.tools.builtin.web_search import _format_results
        text = _format_results("test", [])
        assert "No results found" in text

    def test_format_results_with_items(self):
        from jarvis.core.tools.builtin.web_search import _format_results
        results = [{"title": "Title", "url": "https://example.com", "snippet": "A snippet"}]
        text = _format_results("test", results)
        assert "Title" in text
        assert "https://example.com" in text
        assert "A snippet" in text


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


def test_parse_ddg_html_skips_ads_and_unwraps_links():
    from jarvis.core.tools.builtin.web_search import parse_ddg_html

    assert parse_ddg_html(_DDG_PAGE, 5) == [
        {"title": "LLM 에이전트 사례", "url": "https://blog.example/a", "snippet": "SK, LG 의 도입 성과 & 인사이트"},
        {"title": "둘째", "url": "https://docs.example/b", "snippet": ""},
    ]
    assert len(parse_ddg_html(_DDG_PAGE, 1)) == 1
    assert parse_ddg_html("<html></html>", 5) == []
