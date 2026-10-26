"""lh_notice: 조건을 게시판 폼으로 바꾸고, 목록과 상세를 읽어 KST 기준 마감을 붙인다."""

import re
import pytest
import asyncio

from jarvis.core.tools.housing.lh_notice import (
    MAX_PAGES,
    LhNoticeTool,
    Query,
    build_queries,
    detail_url,
    form_of,
    pages_of,
    parse_detail,
    parse_list,
    resolve_region,
    unit_price,
)
from tests.unit.core.housing.conftest import TODAY, FakeBoard, page


def _run(tool: LhNoticeTool, params: dict) -> tuple[str, bool]:
    result = asyncio.run(tool.execute("t1", params))
    return result.content[0].text, result.is_error


@pytest.mark.parametrize(
    ("name", "code"),
    [("서울", "11"), ("서울특별시", "11"), ("경기", "41"), ("충북", "43"), ("광주", "12"), ("전국", ""), ("", "")],
)
def test_resolve_region(name, code):
    assert resolve_region(name) == code


def test_unknown_region_is_none():
    assert resolve_region("평양") is None


def test_no_category_means_rental_and_sale():
    queries, reason = build_queries({})
    assert reason is None
    assert [q.category for q in queries] == ["임대", "분양"]


def test_subtype_decides_category_and_codes():
    queries, _ = build_queries({"subtype": "행복주택", "category": "토지"})
    assert [(q.category, q.code) for q in queries] == [("임대", "06/10")]
    form = form_of(queries[0], TODAY)
    assert (form["mi"], form["uppAisTpCd"], form["aisTpCd"]) == ("1026", "06", "10")


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({"category": "오피스텔"}, "모르는 공고유형"),
        ({"subtype": "반값아파트"}, "모르는 세부유형"),
        ({"region": "평양"}, "모르는 지역"),
        ({"status": "진행중"}, "모르는 상태"),
        ({"limit": "많이"}, "정수"),
    ],
)
def test_bad_arguments_are_explained(params, fragment):
    queries, reason = build_queries(params)
    assert queries == []
    assert fragment in reason


def test_form_period_and_page_size():
    query = Query("임대", "", "11", "공고중", "청년", None, 20)
    form = form_of(query, TODAY)
    # 게시일 기준 최근 1년, 게시판이 받는 쪽 크기 중 limit 이상인 가장 작은 값
    assert (form["schTy"], form["startDt"], form["endDt"]) == ("0", "2025-10-13", "2026-10-13")
    assert form["listCo"] == "30"
    assert (form["cnpCd"], form["panSs"], form["panNm"]) == ("11", "공고중", "청년")
    closing = form_of(Query("임대", "", "", "", "", 7, 10), TODAY)
    assert (closing["schTy"], closing["startDt"], closing["endDt"]) == ("1", "2026-10-13", "2026-10-20")


def test_later_pages_continue_the_search_instead_of_starting_over():
    query = Query("임대", "", "11", "공고중", "", None, 10, order="마감순")
    first, second = form_of(query, TODAY), form_of(query, TODAY, page=2)
    # 전부 볼 때는 가장 큰 쪽으로 받는다. 2쪽부터 srchY=N 과 앞 쪽 크기가 없으면 게시판이 1쪽을 다시 준다
    assert (first["listCo"], first["srchY"], first["currPage"]) == ("100", "Y", "1")
    assert (second["srchY"], second["prevListCo"], second["currPage"]) == ("N", "100", "2")
    assert {k: v for k, v in second.items() if k not in ("srchY", "prevListCo", "currPage")} == {
        k: v for k, v in first.items() if k not in ("srchY", "prevListCo", "currPage")
    }


@pytest.mark.parametrize(("total", "pages"), [(None, 1), (0, 1), (61, 1), (100, 1), (101, 2), (10_000, MAX_PAGES)])
def test_pages_of_stops_at_total_and_cap(total, pages):
    assert pages_of(total) == pages


def test_exhaustive_search_reads_every_page_once_and_drops_repeats():
    html = re.sub(r"(전체\s*<strong>\s*)[\d,]+", r"\g<1>250", page("lh_list.html"))
    board = FakeBoard({"selectWrtancList.do": html})
    single = parse_list(page("lh_list.html"))[1]
    query = Query("임대", "", "", "", "", None, 10, all_pages=True)
    [(_, total, notices)] = asyncio.run(LhNoticeTool(board, lambda: TODAY).search([query], TODAY))
    assert total == 250
    assert [q["currPage"] for _, q in board.calls] == ["1", "2", "3"]
    assert [n.id for n in notices] == [n.id for n in single]  # 같은 공고가 쪽마다 와도 한 번만


def test_same_query_gives_same_form():
    query = Query("분양", "", "", "", "", None, 10)
    assert form_of(query, TODAY) == form_of(query, TODAY)


def test_parse_list_reads_real_board_rows():
    total, notices = parse_list(page("lh_list.html"))
    assert total == 6
    first = notices[0]
    assert first.id == "2015122300020859-03-39-42"
    assert (first.kind, first.region, first.posted, first.closes, first.status) == (
        "행복주택(신혼희망)", "경기도", "2026.10.01", "2026.10.14", "접수중",
    )
    assert "하남시 신혼희망타운" in first.title and "일전" not in first.title


def test_parse_list_without_board_table():
    assert parse_list("<html>점검 중</html>") == (None, [])


def test_detail_url_menu_by_type():
    assert detail_url("0000061179-02-39-39").endswith("aisTpCd=39&mi=1027")
    assert detail_url("2015122300020859-03-39-42").endswith("mi=1026")
    assert detail_url("0000060001-02-01-").endswith("mi=1062")


def test_parse_detail_reads_units_schedule_and_files():
    detail = parse_detail(page("lh_detail_sale.html"))
    assert detail["title"] == "인천계양 A17블록 신혼희망타운(공공분양) 입주자모집공고"
    assert detail["info"]["마감일"] == "2026.10.27"
    assert detail["units"][0][4] == "평균분양가격(원)"
    assert detail["units"][1][:5] == ["55.9000A", "55.9", "205", "137", "504,484,000"]
    assert "당첨자발표일자 : 2026.11.05" in detail["sections"]["공급일정"]
    assert any(name.endswith(".pdf") for name in detail["files"])


def test_search_lists_with_kst_deadlines(lh_board):
    text, is_error = _run(LhNoticeTool(lh_board, lambda: TODAY), {"category": "신혼희망타운", "status": "공고중"})
    assert not is_error
    assert "KST 2026-10-13 기준" in text
    assert "[D-1] 하남시 신혼희망타운" in text
    assert "[D-14] 인천계양 A17블록" in text
    assert "id 0000061179-02-39-39" in text
    url, form = lh_board.calls[0]
    assert url.endswith("selectWrtancList.do")
    assert (form["mi"], form["srchUppAisTpCd"], form["panSs"]) == ("1026", "39", "공고중")


def test_search_without_category_asks_rental_and_sale(lh_board):
    _run(LhNoticeTool(lh_board, lambda: TODAY), {"limit": 2})
    assert [form["mi"] for _, form in lh_board.calls] == ["1026", "1027"]


def test_limit_cuts_rows(lh_board):
    text, _ = _run(LhNoticeTool(lh_board, lambda: TODAY), {"category": "신혼희망타운", "limit": 1})
    assert text.count("\n- [") == 1


def test_detail_by_id(lh_board):
    text, is_error = _run(LhNoticeTool(lh_board, lambda: TODAY), {"id": "0000061179-02-39-39"})
    assert not is_error
    assert "마감(KST 2026-10-13 기준): D-14" in text
    assert "55.9000A | 55.9 | 205 | 137 | 504,484,000" in text
    _, query = lh_board.calls[0]
    assert query == {"panId": "0000061179", "ccrCnntSysDsCd": "02", "uppAisTpCd": "39", "aisTpCd": "39", "mi": "1027"}


def test_bad_id_is_rejected_without_fetch(lh_board):
    text, is_error = _run(LhNoticeTool(lh_board, lambda: TODAY), {"id": "인천계양"})
    assert is_error and "id 형식" in text
    assert lh_board.calls == []


def test_board_failure_is_an_error_result():
    text, is_error = _run(LhNoticeTool(FakeBoard({}), lambda: TODAY), {"category": "임대"})
    assert is_error and "LH 게시판 조회 실패" in text


def test_unexpected_page_is_an_error_result():
    board = FakeBoard({"selectWrtancList.do": "<html>잠시 후 다시</html>"})
    text, is_error = _run(LhNoticeTool(board, lambda: TODAY), {"category": "임대"})
    assert is_error and "목록 표" in text


def test_deadline_order_puts_soonest_first_and_closed_last(lh_board):
    text, _ = _run(LhNoticeTool(lh_board, lambda: TODAY), {"category": "신혼희망타운", "order": "마감순"})
    labels = [line.split("]")[0].removeprefix("- [") for line in text.splitlines() if line.startswith("- [")]
    assert labels == ["D-1", "D-2", "D-2", "D-14"]
    assert "마감순" in text


def test_results_end_with_next_step_hints(lh_board):
    tool = LhNoticeTool(lh_board, lambda: TODAY)
    assert "링크를 적는다" in _run(tool, {"category": "신혼희망타운"})[0]
    assert "housing_loan 에 notice_id=0000061179-02-39-39" in _run(tool, {"id": "0000061179-02-39-39"})[0]


def test_bad_order_is_explained():
    assert "정렬" in build_queries({"order": "가격순"})[1]


UNITS = [
    ["주택형", "전용면적(㎡)", "세대수", "금회공급 세대수", "평균분양가격(원)", "인터넷청약"],
    ["55.9000A", "55.9", "205", "137", "504,484,000", "청약신청전"],
    ["55.8800B", "55.88", "146", "98", "503,419,000", "청약신청전"],
]


@pytest.mark.parametrize(
    ("unit", "expected"),
    [("55A", "55.9000A"), ("55B", "55.8800B"), ("55b형", "55.8800B"), ("55.88B", "55.8800B"), ("", "55.9000A")],
)
def test_unit_price_matches_area_and_letter(unit, expected):
    assert unit_price(UNITS, unit)[0] == expected


def test_unit_price_reads_deposit_when_no_sale_price():
    rental = [
        ["주택형", "임대보증금(원)", "월임대료(원)"],
        ["000017", "공고문 확인", "공고문 확인"],
        ["000026", "12,000,000", "150,000"],
    ]
    assert unit_price(rental, "") == ("000026", "임대보증금(원)", 12_000_000)
    assert unit_price(rental, "84") is None


def test_price_of_notice(lh_board):
    price, basis = asyncio.run(LhNoticeTool(lh_board, lambda: TODAY).price_of("0000061179-02-39-39", "55B"))
    assert price == 503_419_000
    assert basis == "인천계양 A17블록 신혼희망타운(공공분양) 입주자모집공고 55.8800B 평균분양가격(원)"


def test_price_of_unknown_unit(lh_board):
    with pytest.raises(ValueError, match="주택형: 55.9000A, 55.8800B, 55.7600C"):
        asyncio.run(LhNoticeTool(lh_board, lambda: TODAY).price_of("0000061179-02-39-39", "84A"))


def test_search_without_region_uses_each_home_region(lh_board):
    from types import SimpleNamespace

    from jarvis.core.tools.housing.profile import HousingProfile
    from jarvis.memory.scope import MemoryScope

    class Profiles:
        async def get(self, user_id):
            return HousingProfile(regions=("서울", "경기"))

    tool = LhNoticeTool(lh_board, lambda: TODAY, Profiles())  # type: ignore[arg-type]  # get 만 흉내 낸다
    context = SimpleNamespace(scope=MemoryScope(user_id="u1", agent_id="karen"))
    result = asyncio.run(tool.execute("t1", {"category": "임대", "limit": 1}, None, context))
    text = result.content[0].text
    assert text.startswith("지역을 주지 않아 관심 지역(서울, 경기)으로 찾았다")
    assert [form["cnpCd"] for _, form in lh_board.calls] == ["11", "41"]
    # 지역을 주면 관심 지역은 보지 않는다
    lh_board.calls.clear()
    asyncio.run(tool.execute("t1", {"category": "임대", "region": "부산", "limit": 1}, None, context))
    assert [form["cnpCd"] for _, form in lh_board.calls] == ["26"]
