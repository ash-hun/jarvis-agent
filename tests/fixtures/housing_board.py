"""청약 도구 테스트 공용: 실제 게시판에서 잘라 둔 HTML 과, URL 로 그 HTML 을 돌려주는 가짜 게시판."""

from pathlib import Path
from datetime import date

from jarvis.core.tools.tools_registry import JarvisTool
from jarvis.core.tools.housing.fetch import FetchError
from jarvis.core.tools.housing import housing_tools

FIXTURES = Path(__file__).resolve().parent / "housing"
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


class Board:
    """목록은 신혼희망타운 픽스처, 상세는 공고 id 로 고른다. 첨부와 단지 검색도 흉내 낸다."""

    def __init__(self, pdf_text: str | None = None) -> None:
        self.pdf_text = pdf_text
        self.calls: list[str] = []

    async def fetch(self, url: str, query: dict[str, str]) -> str:
        self.calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("selectWrtancList.do"):
            return page("lh_list.html")
        if url.endswith("selectWrtancInfo.do"):
            if query["panId"] == "0000061179":
                return page("lh_detail_sale.html")
            if query["panId"] == "2015122300020803":
                return page("lh_detail_rental.html")
            return page("lh_detail_rental.html").replace("fileDownLoad", "noFile")
        if url.endswith("ajax.do"):
            return page("complex_gyeonggi.json")
        raise FetchError(url)

    async def fetch_file(self, url: str, query: dict[str, str], referer: str) -> bytes:
        self.calls.append("lhFile.do")
        if self.pdf_text is None:
            raise FetchError("첨부 없음")
        return self.pdf_text.encode()


def budget_tool(board: Board) -> JarvisTool:
    return housing_tools(board.fetch, lambda: TODAY, board.fetch_file, lambda data: data.decode())[3]
