"""housing_budget: 열린 공고를 모아 금액(상세, 공고문 PDF, 단지)을 찾고 예산과 월 상한으로 골라 추천한다."""

import asyncio

import pytest

from jarvis.core.tools.housing import housing_tools
from jarvis.core.tools.housing.budget import Option, Terms, options_from_units, parse_terms, plan_for
from jarvis.core.tools.housing.fetch import FetchError
from jarvis.core.tools.housing.lh_notice import Notice
from tests.unit.core.housing.conftest import TODAY, page

NOTICE = Notice("1-03-06-10", "행복주택", "테스트 공고", "경기도", "2026.10.01", "2026.10.20", "공고중")


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


def _tool(board: Board):
    return housing_tools(board.fetch, lambda: TODAY, board.fetch_file, lambda data: data.decode())[3]


def _run(board: Board, params: dict) -> tuple[str, bool]:
    result = asyncio.run(_tool(board).execute("t1", params))
    return result.content[0].text, result.is_error


def test_parse_terms_defaults_and_regions():
    terms, regions, limit = parse_terms({"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6, "regions": "서울/경기"})
    assert (terms.rate, terms.years, limit) == (4.0, 30, 3)
    assert regions == ["서울", "경기"]
    assert parse_terms({"budget": 1, "cash": 0})[1] == ["전국"]


@pytest.mark.parametrize(
    "params", [{"budget": 0, "cash": 1}, {"budget": 1, "cash": -1}, {"budget": 1, "cash": 0, "regions": "평양"}]
)
def test_bad_terms(params):
    with pytest.raises(ValueError):
        parse_terms(params)


def test_options_from_units_skip_unpriced_cells():
    rental = [["주택형", "임대보증금(원)", "월임대료(원)"], ["26A", "공고문 확인", "공고문 확인"]]
    assert options_from_units(rental) == []
    sale = options_from_units([["주택형", "평균분양가격(원)"], ["55A", "504,484,000"]])
    assert sale == [Option("55A", 504_484_000, 0, True, "공고 상세")]


def test_plan_picks_cheapest_fitting_unit_and_counts_fits():
    terms = Terms(budget=3e8, cash=1.2e8, monthly_limit=2e6, rate=4.0, years=30)
    options = [
        Option("big", 290_000_000, 500_000, False, "x"),
        Option("small", 100_000_000, 300_000, False, "x"),
        Option("too much", 310_000_000, 0, False, "x"),
    ]
    plan = plan_for(NOTICE, options, terms)
    assert plan.option.unit == "small" and plan.loan == 0 and plan.monthly == 300_000
    assert plan.fits == 2


def test_rental_deposit_loan_pays_interest_only():
    terms = Terms(budget=3e8, cash=1.2e8, monthly_limit=None, rate=4.0, years=30)
    plan = plan_for(NOTICE, [Option("55A1", 174_800_000, 684_630, False, "x")], terms)
    assert round(plan.repay) == 182_667 and round(plan.monthly) == 867_297


def test_monthly_limit_excludes_everything():
    terms = Terms(budget=6e8, cash=1e8, monthly_limit=100_000, rate=4.0, years=30)
    assert plan_for(NOTICE, [Option("55A", 504_484_000, 0, True, "x")], terms) is None


def test_recommends_from_pdf_and_lists_unknown_and_over_budget():
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    text, is_error = _run(board, {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6})
    assert not is_error
    assert "조건에 맞는 공고 1건" in text
    assert "[D-2] 의왕청계2 A1블록 신혼희망타운 행복주택 입주자 모집공고" in text
    assert "55A1 보증금 174,800,000원" in text and "(공고문 PDF 임대조건)" in text
    assert "월 부담 867,297원" in text
    # 분양가 5억은 예산 3억을 넘는다
    assert "예산이나 월 상한을 넘는 공고 1건: 인천계양 A17블록" in text
    # 하남(블록 없음)과 세종은 금액을 찾지 못한다
    assert "금액을 찾지 못한 공고 2건" in text
    assert "가정: 연 4%" in text


def test_bigger_budget_includes_sale_sorted_by_monthly():
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    text, _ = _run(board, {"budget": 6e8, "cash": 1.5e8, "monthly_limit": 2.5e6, "limit": 5})
    first, second = text.index("의왕청계2"), text.index("인천계양 A17블록")
    assert first < second  # 월 부담 작은 순
    assert "55.8800B 분양가 503,419,000원" in text and "월 부담 1,687,276원" in text


def test_pdf_failure_falls_back_without_crashing():
    board = Board(pdf_text=None)
    text, is_error = _run(board, {"budget": 3e8, "cash": 1.2e8})
    assert not is_error
    assert "조건에 맞는 공고 0건" in text and "금액을 찾지 못한 공고 3건" in text


def test_same_day_same_answer():
    params = {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6}
    assert _run(Board(page("rent_terms_uiwang.txt")), params) == _run(Board(page("rent_terms_uiwang.txt")), params)
