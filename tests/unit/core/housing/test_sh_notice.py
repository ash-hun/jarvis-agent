"""sh_notice: SH 게시판 목록과 상세, 검색어 규칙, 제목으로 짐작한 상태, 첨부 메타데이터."""

import asyncio

from jarvis.core.tools.housing.sh_notice import (
    BOARDS,
    ShNoticeTool,
    list_query,
    parse_attachments,
    parse_detail,
    parse_list,
    title_status,
    view_url,
)
from tests.fixtures.housing_board import FakeBoard, page


def _run(tool: ShNoticeTool, params: dict) -> tuple[str, bool]:
    result = asyncio.run(tool.execute("t1", params))
    return result.content[0].text, result.is_error


def test_keyword_always_sends_search_type():
    assert list_query(BOARDS["임대"], "행복주택", "제목", 1) == {
        "multi_itm_seq": "2", "page": "1", "srchWord": "행복주택", "srchTp": "0",
    }
    assert list_query(BOARDS["임대"], "장기전세", "본문", 2)["srchTp"] == "1"
    assert "srchTp" not in list_query(BOARDS["임대"], "", "제목", 1)


def test_title_status_guess():
    assert title_status("행복주택 예비당첨자 게시") == "당첨/발표"
    assert title_status("행복주택 최종 청약 경쟁률 게시") == "마감/결과"
    assert title_status("2026년 장기전세주택 입주자 모집공고") == "모집/접수"
    assert title_status("홈페이지 안내") == "알 수 없음"


def test_parse_list_reads_real_rows():
    total, posts = parse_list(page("sh_list.html"))
    assert total == 94
    assert posts[0].seq == "310563"
    assert posts[0].title == "2026년 2차 행복주택 서류심사 대상자 발표 및 서류 제출 안내"
    assert (posts[0].department, posts[0].registered) == ("공공주택공급부", "2026-09-21")


def test_parse_list_blocked_page_is_none():
    assert parse_list("<html>NetFunnel 대기열</html>") is None


def test_detail_reads_body_and_downlist_attachments():
    detail = parse_detail(page("sh_detail.html"))
    assert detail["title"] == "2026년 2차 행복주택 서류심사 대상자 발표 및 서류 제출 안내"
    assert (detail["registered"], detail["department"]) == ("2026-09-21", "공공주택공급부")
    assert "서류심사 대상자 명단" in detail["content"]
    first = detail["attachments"][0]
    assert first["name"] == "(0) 행복주택 심사 서류 제출 안내문.pdf"
    assert first["preview"].endswith("htmlConverter.do?brd_id=GS0401&seq=310563&data_tp=A&file_seq=35")


def test_icon_templates_are_not_attachments():
    # 확장자 아이콘 견본 앵커만 있고 downList 가 없으면 첨부는 없다
    assert parse_attachments('<a href="#" class="btnAttach v1">.pdf</a>') == []


def test_view_url_for_category_and_all_board():
    assert view_url(BOARDS["임대"], "1").endswith("m_247/view.do?multi_itm_seq=2&seq=1")
    assert view_url(BOARDS["전체"], "1").endswith("m_241/view.do?seq=1")


def test_search_tool(sh_board):
    text, is_error = _run(ShNoticeTool(sh_board), {"keyword": "행복주택"})
    assert not is_error
    assert "SH 공고 (주택임대, 제목 '행복주택', 1쪽). 전체 94건" in text
    assert "seq 310563" in text
    assert sh_board.calls[0][1]["srchTp"] == "0"


def test_status_filter_says_it_is_a_guess(sh_board):
    text, _ = _run(ShNoticeTool(sh_board), {"keyword": "행복주택", "status": "마감/결과"})
    assert "제목 말로 짐작" in text
    assert "경쟁률" in text and "서류심사" not in text


def test_welfare_maps_to_purchase_board(sh_board):
    text, _ = _run(ShNoticeTool(sh_board), {"category": "주거복지"})
    assert sh_board.calls[0][1]["multi_itm_seq"] == "512"
    assert "주택매입' 분류" in text


def test_detail_tool(sh_board):
    text, is_error = _run(ShNoticeTool(sh_board), {"seq": "310563"})
    assert not is_error
    assert "담당 공공주택공급부" in text
    assert "(1) 2026년 2차 행복주택 서류심사 대상자 합격선.pdf" in text
    assert sh_board.calls[0][1] == {"multi_itm_seq": "2", "seq": "310563"}


def test_bad_arguments(sh_board):
    assert _run(ShNoticeTool(sh_board), {"category": "오피스텔"})[1]
    assert _run(ShNoticeTool(sh_board), {"seq": "12a"})[1]
    assert sh_board.calls == []


def test_board_failure_is_an_error_result():
    text, is_error = _run(ShNoticeTool(FakeBoard({})), {"keyword": "행복주택"})
    assert is_error and "SH 게시판 조회 실패" in text
