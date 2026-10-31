"""housing: housing_budget 이 열린 LH, SH 공고 금액으로 대출 경우를 펼쳐 추천하고 1순위 마감 전 약속을 남기는지 검증."""

import pytest
import asyncio
from datetime import date
from dataclasses import replace

from jarvis.core.tools.housing.budget import CONCURRENCY, Option, Terms, options_from_sh, options_from_units
from jarvis.core.tools.housing.budget import parse_terms, plan_for, top_pick
from tests.fixtures.housing_board import TODAY, Board, budget_tool, page
from jarvis.core.tools.housing.rules import NO, Verdict, load_rules
from jarvis.agent_layer.openloop import InMemoryOpenLoopStore
from jarvis.core.tools.housing.profile import HousingProfile
from jarvis.core.tools.housing.sh_notice import parse_list
from jarvis.core.tools.housing.sh_terms import sale_units
from jarvis.core.tools.tools_registry import ToolContext
from jarvis.core.tools.housing.fetch import FetchError
from jarvis.core.tools.housing.lh_notice import Notice
from jarvis.core.tools.housing import housing_tools
from jarvis.memory.scope import MemoryScope

NOTICE = Notice("1-03-06-10", "행복주택", "테스트 공고", "경기도", "2026.10.01", "2026.10.20", "공고중")
RECRUIT_TITLE = "2026년 3차 희망하우징(공공기숙사) 잔여세대 입주자 모집공고"
PARAMS = {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6}

def _run(board: Board, params: dict) -> tuple[str, bool]:
    result = asyncio.run(budget_tool(board).execute("t1", params))
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
def test_parse_terms_rejects_bad_terms(params):
    with pytest.raises(ValueError):
        parse_terms(params)


def test_options_from_units_skip_unpriced_cells():
    rental = [["주택형", "임대보증금(원)", "월임대료(원)"], ["26A", "공고문 확인", "공고문 확인"]]
    assert options_from_units(rental) == []
    sale = options_from_units([["주택형", "평균분양가격(원)"], ["55A", "504,484,000"]])
    assert sale == [Option("55A", 504_484_000, 0, True, "공고 상세")]


def test_plan_for_prefers_fitting_cheapest_unit():
    options = [Option("big", 290_000_000, 500_000, False, "x"), Option("small", 100_000_000, 300_000, False, "x")]
    plan = plan_for(NOTICE, options, Terms(1.2e8, 2e6, None, None, None), load_rules(), HousingProfile(), TODAY)
    assert plan.option.unit == "small" and plan.fitted and plan.best.monthly == 300_000
    assert (plan.fits, plan.units) == (2, 2)


def test_plan_for_without_fit_keeps_the_nearest_case():
    options = [Option("55A", 504_484_000, 0, True, "x")]
    plan = plan_for(NOTICE, options, Terms(1e8, 1e5, None, None, None), load_rules(), HousingProfile(), TODAY)
    assert not plan.fitted and plan.fits == 0 and plan.best.shortfall > 0


def test_tool_recommends_rentals_with_products_and_conversions():
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


def test_tool_sale_near_miss_shows_policy_and_market_loans():
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    text, _ = _run(board, {"cash": "1억 5천", "monthly_limit": "250만"})
    sale = text[text.index("[분양(구입 대출)]"):text.index("[임대(보증금 대출)]")]
    assert "맞는 경우가 있는 공고 0건" in sale and "가장 가까운 주택형" in sale
    assert "보금자리론 연 5.1% 30년 원리금균등:" in sale and "(한도 3억 5,239만원 = 최소(" in sale
    assert "현금 부족 103만원" in sale
    assert "디딤돌 대출" in sale and "불가(집값 5억원 이하)" in sale


def test_tool_conditions_apply_profile_for_this_call():
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    conditions = "무주택=예, 생애최초=미사용, 혼인=미혼, 연소득=6000만, 나이=28"
    text, _ = _run(board, {"cash": "1억 5천", "monthly_limit": "250만", "conditions": conditions})
    assert "프로필로 자격이 안 되어 뺀 상품: 디딤돌 대출(만 30세 미만 미혼 단독세대주 제외" in text
    assert "버팀목 전세자금대출(연소득 5,000만원 이하)" in text
    assert "이번 계산에만 조건을 덧씌움" in text
    assert "· 버팀목 전세자금대출" not in text


def test_tool_pdf_failure_falls_back_without_crashing():
    board = Board(pdf_text=None)
    text, is_error = _run(board, {"budget": 3e8, "cash": 1.2e8})
    assert not is_error
    assert "맞는 경우가 있는 공고 0건" in text and "금액을 찾지 못한 공고 3건" in text


def test_tool_same_day_same_answer():
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


def test_tool_parallel_details_keep_the_deadline_order_and_the_limit():
    params = {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6}
    slow = SlowBoard(page("rent_terms_uiwang.txt"))
    assert _run(slow, params) == _run(Board(page("rent_terms_uiwang.txt")), params)
    assert 1 < slow.peak <= CONCURRENCY


def test_tool_case_lines_stand_alone_and_show_access():
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


def test_tool_result_is_the_final_answer_but_errors_are_not():
    """계산 결과는 모델이 옮기지 않고 그대로 답이 된다. 오류는 모델이 받아 다시 부르거나 설명한다."""
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    ok = asyncio.run(budget_tool(board).execute("t1", {"cash": "1억 5천"}))
    bad = asyncio.run(budget_tool(board).execute("t2", {"cash": "많이"}))
    assert ok.final and not ok.is_error
    assert bad.is_error and not bad.final
    assert "답할 때" not in ok.content[0].text and "알려 주면 자격을 가려 다시 계산한다" in ok.content[0].text


def test_parse_terms_without_regions_uses_the_home_regions():
    home = HousingProfile(regions=("서울", "경기"))
    assert parse_terms({"cash": "1억"}, home)[1] == ["서울", "경기"]
    assert parse_terms({"cash": "1억", "regions": "부산"}, home)[1] == ["부산"]
    assert parse_terms({"cash": "1억"})[1] == ["전국"]


def test_tool_one_top_pick_per_group_comes_before_the_lists():
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    text, _ = _run(board, {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6})
    pick = next(line for line in text.splitlines() if line.startswith("추천 1순위(임대)"))
    assert "의왕청계2 A1블록" in pick and "월 부담 최대" in pick and "월 여유" in pick and "마감 " in pick
    # 분양은 총액 상한에 걸려 고를 것이 없다
    assert "추천 1순위(분양): 없음" in text
    assert text.index("추천 1순위(임대)") < text.index("[분양(구입 대출)]")


def test_top_pick_skips_unlikely_and_unfit_plans_and_breaks_ties_by_deadline():
    terms = Terms(1.2e8, 2e6, None, None, None)
    plan = plan_for(NOTICE, [Option("s", 1e8, 300_000, False, "x")], terms, load_rules(), HousingProfile(), TODAY)
    later = replace(plan, notice=replace(NOTICE, title="늦게 마감", closes="2026.12.01"))
    unlikely = replace(plan, access=Verdict(NO, ("신혼부부 대상",)))
    assert top_pick([later, plan]) is plan  # 같은 조건이면 마감이 이른 쪽
    assert top_pick([unlikely]) is None and top_pick([replace(plan, fitted=False)]) is None


def test_tool_answer_opens_with_karens_one_line_conclusion():
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    text, _ = _run(board, {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6})
    lead = "애쉬, 전국에서 이 조건에 맞는 공고는 분양 0건, 임대 1건이에요. 아래 추천 1순위부터 보시면 돼요."
    assert text.splitlines()[0] == lead


def test_tool_picks_only_gives_copyable_keyed_items_with_full_links():
    """목표 차례용: 결론과 조건 줄, 1순위마다 키와 전체 링크가 붙은 한 줄. 모델이 링크를 줄이던 것을 막는다."""
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    text, is_error = _run(board, {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6, "picks_only": True})
    lines = text.splitlines()
    assert not is_error and lines[0].startswith("애쉬,") and lines[1].startswith("LH 공고 대출 경우의 수")
    assert "추천 1순위(분양): 없음" in lines
    rent = next(line for line in lines if line.startswith("추천 1순위(임대) 항목: ["))
    assert "의왕청계2 A1블록" in rent and "월 부담 최대" in rent and "panId=" in rent and "&mi=" in rent
    assert "현금 " in rent and ("+ 현금" in rent or "대출 없이" in rent)
    assert "[분양(구입 대출)]" not in text


def test_tool_picks_only_without_cash_gives_the_ask_item_to_copy():
    """목표 차례에서 현금을 모르면 물을 항목 줄을 도구가 준다. 모델이 지으면 키 없이 말만 써 알리지 못했다."""
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    text, is_error = _run(board, {"picks_only": True})
    assert not is_error and "항목: [ask-money] " in text
    text, is_error = _run(board, {})
    assert is_error and "ask-money" not in text


def tracking_tool(store: InMemoryOpenLoopStore):
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    return housing_tools(board.fetch, lambda: TODAY, board.fetch_file, lambda data: data.decode(), loops=store)[3]


def context_for(session_id: str) -> ToolContext:
    return ToolContext(scope=MemoryScope(user_id="u", agent_id="karen", session_id=session_id), session_id=session_id)


def test_tool_leaves_one_deadline_loop_for_the_top_pick_and_says_so_once():
    store = InMemoryOpenLoopStore()
    tool = tracking_tool(store)

    text = asyncio.run(tool.execute("t1", PARAMS, context=context_for("s1"))).content[0].text
    again = asyncio.run(tool.execute("t2", PARAMS, context=context_for("s1"))).content[0].text

    [loop] = asyncio.run(store.list_open(session_id="s1"))
    assert "의왕청계2 A1블록" in loop.description and loop.agent_id == "karen"
    assert text.endswith("마감 3일 전 아침에 다시 알려 드릴게요.") and date.fromtimestamp(loop.due_ms / 1000) > TODAY
    # 같은 추천을 다시 받아도 약속은 하나이고, 다시 알리겠다는 말도 되풀이하지 않는다
    assert len(asyncio.run(store.all())) == 1 and "다시 알려 드릴게요" not in again


def test_tool_in_scheduled_and_test_sessions_leaves_no_deadline_loop():
    """목표 차례(sched-)와 시험 세션은 끝나면 아무도 약속을 꺼내지 않는다. 남기지 않고, 결과 글도 매번 같다."""
    store = InMemoryOpenLoopStore()
    tool = tracking_tool(store)

    texts = [
        asyncio.run(tool.execute("t", PARAMS, context=context_for(sid))).content[0].text
        for sid in ("sched-goal-abc-1", "sched-goal-abc-2", "test-goal-1")
    ]

    assert asyncio.run(store.all()) == [] and len(set(texts)) == 1 and "다시 알려 드릴게요" not in texts[0]


class ShBoard(Board):
    """LH 는 housing_budget 테스트의 가짜 게시판 그대로, SH 는 모집 글 하나와 그 공고문(임대 금액)을 준다."""

    def __init__(self) -> None:
        super().__init__()
        listing = page("sh_list.html")
        _, posts = parse_list(listing)  # type: ignore[misc]
        self.list_html = listing.replace(posts[0].title, RECRUIT_TITLE)
        notice_file = "(0) 행복주택 심사 서류 제출 안내문.pdf"
        self.detail_html = page("sh_detail.html").replace(notice_file, "입주자 모집공고문.pdf")
        self.files: list[dict[str, str]] = []

    async def fetch(self, url: str, query: dict[str, str]) -> str:
        if "i-sh.co.kr" in url:
            return self.list_html if url.endswith("list.do") else self.detail_html
        return await super().fetch(url, query)

    async def fetch_file(self, url: str, query: dict[str, str], referer: str) -> bytes:
        if "i-sh.co.kr" not in url:
            raise FetchError("LH 첨부 없음")
        self.files.append(query)
        return page("sh_rent_terms.txt").encode()


def test_tool_includes_seoul_sh_notices_with_their_own_link_and_key():
    board = ShBoard()
    tool = housing_tools(board.fetch, lambda: TODAY, board.fetch_file, lambda data: data.decode())[3]
    params = {"cash": "1억", "monthly_limit": "100만원", "regions": "서울", "picks_only": True}

    result = asyncio.run(tool.execute("t", params))

    text = result.content[0].text
    assert not result.is_error and text.splitlines()[1].startswith("LH, SH 공고 대출 경우의 수")
    pick = next(line for line in text.splitlines() if line.startswith("추천 1순위(임대) 항목: [sh-310563]"))
    # 금액이 가장 싼 경우(희망하우징 보증금 109만원, 월 9만 900원)가 1순위다. 링크는 SH 글
    assert "정릉 희망하우징" in pick and "i-sh.co.kr" in pick and "seq=310563" in pick
    assert board.files and board.files[0]["seq"] == "310563"
    # 경기만 물으면 SH 를 보지 않는다
    board.files.clear()
    asyncio.run(tool.execute("t", {"cash": "1억", "regions": "경기"}))
    assert board.files == []


def test_plan_for_land_lease_sale_adds_monthly_land_rent_to_every_case():
    """토지임대부 분양은 대출 상환에 월 토지임대료를 더한 것이 월 부담이다."""
    rules = load_rules()
    title = "고덕강일지구 3단지 토지임대부 분양주택 입주자모집공고"
    notice = Notice("sh-312005", "SH 분양", title, "서울특별시", "", "", "공고중")
    options = options_from_sh(sale_units(page("sh_sale_terms_godeok.txt")), notice, rules)
    terms = Terms(cash=150_000_000, monthly_limit=None, budget=None, rate=None, years=None)

    plan = plan_for(notice, options, terms, rules, HousingProfile(), TODAY)

    assert plan is not None and plan.option.rent in (426_000, 511_500)
    assert all(c.rent == plan.option.rent for c in plan.cases)
    assert plan.best.monthly == plan.best.pay[1] + plan.option.rent
