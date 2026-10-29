"""SH 공고문 금액 읽기(임대 금액 쌍, 동호별 분양가, 토지임대료), 모집 글 고르기, housing_budget 에 SH 가 들어가는 길."""

import asyncio

from jarvis.core.tools.housing.sh_terms import close_date, land_rents, pick_sh_pdf, recruiting, rent_units, sale_units
from jarvis.core.tools.housing.budget import Terms, options_from_sh, plan_for
from jarvis.core.tools.housing.sh_notice import Post, parse_list
from jarvis.core.tools.housing.profile import HousingProfile
from tests.unit.core.housing.conftest import TODAY, page
from jarvis.core.tools.housing.fetch import FetchError
from jarvis.core.tools.housing.lh_notice import Notice
from jarvis.core.tools.housing.rules import load_rules
from tests.unit.core.housing.test_budget import Board
from jarvis.core.tools.housing import housing_tools

RECRUIT_TITLE = "2026년 3차 희망하우징(공공기숙사) 잔여세대 입주자 모집공고"


def test_rent_units_read_deposit_and_rent_pairs_but_not_income_tables():
    units = {(u.price, u.rent): u.unit for u in rent_units(page("sh_rent_terms.txt"))}
    # 구로구 도전숙: 소득 구간이 둘이면 비싼 뒤 쌍. 같은 금액의 호수는 하나로 묶는다
    assert units[(47_780_000, 492_300)].startswith("604")
    assert (28_660_000, 295_400) not in units
    assert (37_620_000, 388_000) in units
    # 희망하우징('원1,090,000 원 90,900'), 옥류서원(관리비 칸 앞의 쌍), 장안(한 줄)
    assert units[(1_090_000, 90_900)] == "정릉 희망하우징"
    assert {(190_000_000, 790_000), (194_000_000, 810_000), (97_000_000, 457_000)} <= set(units)
    # 소득 기준표 '2,669,354 4,106,389 5,717,900' 은 보증금, 월임대료 쌍이 아니다
    assert not any(deposit == 2_669_354 or rent == 4_106_389 for deposit, rent in units)


def test_sale_units_group_unit_prices_and_add_land_rent():
    text = page("sh_sale_terms_godeok.txt")
    units = {u.unit: u for u in sale_units(text)}
    assert set(units) == {"59B", "49F"}
    # 단위는 표 머리의 주택가격(천원). 가격 = 계약금 + 잔금 인 행만 읽는다('471,460 4,243,140' 합계 줄은 아니다)
    assert (units["59B"].low, units["59B"].price) == (363_961_000, 386_709_000)
    assert (units["49F"].low, units["49F"].price) == (301_842_000, 314_162_000)
    assert (units["59B"].rent, units["49F"].rent) == (511_500, 426_000)
    assert land_rents(text) == {49: 426_000, 59: 511_500}
    assert land_rents("토지임대료 표 없음") == {}


def test_recruiting_keeps_recent_recruitment_posts_only():
    posts = [
        Post("1", RECRUIT_TITLE, "부", "2026-10-01", "1", "모집/접수"),
        Post("2", "제50차 장기전세주택 입주자 모집공고 계약 안내", "부", "2026-10-01", "1", "모집/접수"),
        Post("3", "행복주택 예비당첨자 게시", "부", "2026-10-01", "1", "당첨/발표"),
        Post("4", "2025년 행복주택 입주자 모집공고", "부", "2026-01-01", "1", "모집/접수"),
    ]
    notices = recruiting(posts, "임대", TODAY)
    assert [(n.id, n.kind, n.region) for n in notices] == [("sh-1", "SH 임대", "서울특별시")]


def test_close_date_is_the_latest_date_of_the_application_paragraph():
    content = (
        "■ 모집공고일: 2026. 10. 28.(수)\n■ 접수일\n○ 인터넷접수: 2026. 11. 9.(월) 10:00 ~ 2026. 11. 11.(수) 17:00\n"
        "■ 서류심사대상자 발표: 2026. 11. 13.(금)"
    )
    assert close_date(content) == "2026.11.11"
    assert close_date("본문에 접수 기간이 없다") == ""


def test_pick_sh_pdf_prefers_the_notice_over_forms():
    files = [
        {"name": "(서식1)신청서.pdf", "download": "a"},
        {"name": "붙임 2026년 서리풀청년아트타운 입주자모집 공고문.pdf", "download": "b"},
        {"name": "신청 관련 부모 범위 기준.pdf", "download": "c"},
    ]
    assert pick_sh_pdf(files)["download"] == "b"  # type: ignore[index]
    assert pick_sh_pdf([{"name": "신청서.hwp", "download": "x"}]) is None


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


def test_budget_includes_seoul_sh_notices_with_their_own_link_and_key():
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


def test_land_lease_sale_adds_monthly_land_rent_to_every_case():
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
