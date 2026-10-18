"""청약 도구 테스트 공용: 실제 게시판에서 잘라 둔 HTML 과, URL 로 그 HTML 을 돌려주는 가짜 fetch."""

import pytest
from pathlib import Path
from datetime import date

from jarvis.core.tools.housing.fetch import FetchError

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "housing"
TODAY = date(2026, 10, 13)


def page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeBoard:
    """URL 끝 경로로 고정 HTML 을 고르고 받은 질의를 남긴다. pages 에 없는 경로는 FetchError."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def __call__(self, url: str, query: dict[str, str]) -> str:
        self.calls.append((url, dict(query)))
        for suffix, html in self.pages.items():
            if url.endswith(suffix):
                return html
        raise FetchError(f"{url} 가 HTTP 503 로 답했다")


@pytest.fixture
def lh_board() -> FakeBoard:
    return FakeBoard({"selectWrtancList.do": page("lh_list.html"), "selectWrtancInfo.do": page("lh_detail_sale.html")})


@pytest.fixture
def sh_board() -> FakeBoard:
    return FakeBoard({"list.do": page("sh_list.html"), "view.do": page("sh_detail.html")})
