"""housing_budget: 열린 공고의 금액을 찾아 대출 경우(상품, 규제, 보증금 전환, 현금 투입)를 펼쳐 추천한다."""

import pytest
import asyncio

from jarvis.core.tools.housing.budget import CONCURRENCY, Option, Terms, excluded_by_profile, options_from_units
from jarvis.core.tools.housing.budget import parse_terms, plan_for
from jarvis.core.tools.housing.profile import HousingProfile
from tests.unit.core.housing.conftest import TODAY, page
from jarvis.core.tools.housing.fetch import FetchError
from jarvis.core.tools.housing.lh_notice import Notice
from jarvis.core.tools.housing.rules import load_rules
from jarvis.core.tools.housing import housing_tools

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


def test_parse_terms_reads_spoken_amounts_and_leaves_rate_to_products():
    terms, regions, limit = parse_terms({"cash": "1억 5천", "monthly_limit": "200만원", "regions": "서울/경기"})
    assert (terms.cash, terms.monthly_limit, terms.budget) == (150_000_000, 2_000_000, None)
    assert (terms.rate, terms.years, limit) == (None, None, 3)
    assert regions == ["서울", "경기"]
    assert parse_terms({"cash": 0})[1] == ["전국"]


@pytest.mark.parametrize(
    "params",
    [
        {"cash": -1}, {"cash": 1, "budget": -5}, {"cash": 1, "regions": "평양"}, {"cash": "많이"},
        {"cash": 1, "years": 70},
    ],
)
def test_bad_terms(params):
    with pytest.raises(ValueError):
        parse_terms(params)


def test_options_from_units_skip_unpriced_cells():
    rental = [["주택형", "임대보증금(원)", "월임대료(원)"], ["26A", "공고문 확인", "공고문 확인"]]
    assert options_from_units(rental) == []
    sale = options_from_units([["주택형", "평균분양가격(원)"], ["55A", "504,484,000"]])
    assert sale == [Option("55A", 504_484_000, 0, True, "공고 상세")]


def test_profile_drops_supply_groups_that_do_not_match():
    single = HousingProfile(married=False, age=28)
    assert excluded_by_profile("44A 신혼부부", single, TODAY)
    assert not excluded_by_profile("44A 신혼부부·한부모가족", single, TODAY)
    assert excluded_by_profile("26B 고령자", single, TODAY)
    assert not excluded_by_profile("26B 고령자", HousingProfile(), TODAY)


def test_plan_prefers_fitting_cheapest_unit():
    options = [Option("big", 290_000_000, 500_000, False, "x"), Option("small", 100_000_000, 300_000, False, "x")]
    plan = plan_for(NOTICE, options, Terms(1.2e8, 2e6, None, None, None), load_rules(), HousingProfile(), TODAY)
    assert plan.option.unit == "small" and plan.fitted and plan.best.monthly == 300_000
    assert (plan.fits, plan.units) == (2, 2)


def test_plan_without_fit_keeps_the_nearest_case():
    options = [Option("55A", 504_484_000, 0, True, "x")]
    plan = plan_for(NOTICE, options, Terms(1e8, 1e5, None, None, None), load_rules(), HousingProfile(), TODAY)
    assert not plan.fitted and plan.fits == 0 and plan.best.shortfall > 0


def test_recommends_rentals_with_products_and_conversions():
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    text, is_error = _run(board, {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6})
    assert not is_error
    assert "현금 120,000,000원(1억 2,000만원), 월 여유자금 200만원, 총액 상한 3억원" in text
    assert "[임대(보증금 대출)] 금액을 아는 공고 1건 중 맞는 경우가 있는 공고 1건" in text
    assert "[D-2] 의왕청계2 A1블록 신혼희망타운 행복주택 입주자 모집공고" in text
    assert "55A1 보증금 1억 7,480만원, 월임대료 684,630원 (공고문 PDF 임대조건)" in text
    assert "수도권, 규제지역" in text  # 의왕은 10.15 규제지역
    assert "시중은행 전세자금대출(HF 보증) 연 4.28~4.81% 만기일시(이자만)" in text
    assert "대출 5,480만원, 현금 1억 2,000만원 → 월 이자 195,453~219,657원 + 월임대료 684,630원" in text
    assert "보증금 증액 전환(보증금 2억 5,680만원, 월임대료 274,630원)" in text
    # 프로필이 없으면 정책 상품을 빼지 않고 자격 확인 조건을 붙인다
    assert "프로필에 없어 자격을 확정하지 못한 상품" in text and "자격 확인: 무주택자만" in text
    # 분양가 5억은 총액 상한 3억을 넘는다
    assert "총액 상한으로 계산할 주택형이 없는 공고 1건: 인천계양 A17블록" in text
    assert "금액을 찾지 못한 공고 2건" in text
    assert "출처: 버팀목 전세자금대출 https://nhuf.molit.go.kr" in text


def test_sale_near_miss_shows_policy_and_market_loans():
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    text, _ = _run(board, {"cash": "1억 5천", "monthly_limit": "250만"})
    sale = text[text.index("[분양(구입 대출)]"):text.index("[임대(보증금 대출)]")]
    assert "맞는 경우가 있는 공고 0건" in sale and "가장 가까운 주택형" in sale
    assert "보금자리론 연 5.1% 30년 원리금균등:" in sale and "(한도 3억 5,239만원 = 최소(" in sale
    assert "현금 부족 103만원" in sale
    assert "디딤돌 대출" in sale and "불가(집값 5억원 이하)" in sale


def test_conditions_apply_profile_for_this_call():
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    conditions = "무주택=예, 생애최초=미사용, 혼인=미혼, 연소득=6000만, 나이=28"
    text, _ = _run(board, {"cash": "1억 5천", "monthly_limit": "250만", "conditions": conditions})
    assert "프로필로 자격이 안 되어 뺀 상품: 디딤돌 대출(만 30세 미만 미혼 단독세대주 제외" in text
    assert "버팀목 전세자금대출(연소득 5,000만원 이하)" in text
    assert "이번 계산에만 조건을 덧씌움" in text
    assert "· 버팀목 전세자금대출" not in text


def test_pdf_failure_falls_back_without_crashing():
    board = Board(pdf_text=None)
    text, is_error = _run(board, {"budget": 3e8, "cash": 1.2e8})
    assert not is_error
    assert "맞는 경우가 있는 공고 0건" in text and "금액을 찾지 못한 공고 3건" in text


def test_same_day_same_answer():
    params = {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6}
    assert _run(Board(page("rent_terms_uiwang.txt")), params) == _run(Board(page("rent_terms_uiwang.txt")), params)


class SlowBoard(Board):
    """상세가 거꾸로 늦게 온다(먼저 부른 것이 가장 늦다). 동시에 열린 요청 수를 잰다."""

    def __init__(self, pdf_text: str | None = None) -> None:
        super().__init__(pdf_text)
        self.open = 0
        self.peak = 0
        self.order = 0

    async def fetch(self, url: str, query: dict[str, str]) -> str:
        if not url.endswith("selectWrtancInfo.do"):
            return await super().fetch(url, query)
        self.order += 1
        self.open += 1
        self.peak = max(self.peak, self.open)
        await asyncio.sleep(0.01 * (10 - self.order))
        self.open -= 1
        return await super().fetch(url, query)


def test_parallel_details_keep_the_deadline_order_and_the_limit():
    params = {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6}
    slow = SlowBoard(page("rent_terms_uiwang.txt"))
    assert _run(slow, params) == _run(Board(page("rent_terms_uiwang.txt")), params)
    assert 1 < slow.peak <= CONCURRENCY


def test_case_lines_stand_alone_and_show_access():
    """상품 하나가 한 줄이고 그 줄에 금리, 경우별 이자와 원금이 있다. 공고마다 신청 가능성을 적는다."""
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    conditions = "무주택=예, 생애최초=미사용, 혼인=미혼, 연소득=6000만, 나이=28"
    text, _ = _run(board, {"cash": "1억 5천", "monthly_limit": "250만", "conditions": conditions})
    assert (
        "· 보금자리론 연 5.1% 30년 원리금균등: 현금 최대 투입 대출 3억 5,239만원, 현금 1억 5,000만원 투입"
        " → 월 1,913,319원 = 이자 1,497,672원 + 원금 415,647원(금리 상단, 첫 달)"
    ) in text
    assert "· 시중은행 주택담보대출 연 4.66~6% 30년 원리금균등: 현금 최대 투입" in text
    assert "· 시중은행 전세자금대출(HF 보증) 연 4.28~4.81% 만기일시(이자만): 대출 2,480만원" in text
    assert "마감 2026.10.27" in text
    assert "신청 가능성 낮음: 미혼이면 예비신혼부부(입주 때까지 혼인 증명)로만 신청할 수 있다" in text


def test_result_is_the_answer_but_errors_are_not():
    """계산 결과는 모델이 옮기지 않고 그대로 답이 된다. 오류는 모델이 받아 다시 부르거나 설명한다."""
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    ok = asyncio.run(_tool(board).execute("t1", {"cash": "1억 5천"}))
    bad = asyncio.run(_tool(board).execute("t2", {"cash": "많이"}))
    assert ok.final and not ok.is_error
    assert bad.is_error and not bad.final
    assert "답할 때" not in ok.content[0].text and "알려 주면 자격을 가려 다시 계산한다" in ok.content[0].text
