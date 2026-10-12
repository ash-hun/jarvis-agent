"""게시판 HTML 을 푸는 순수 함수: 날짜, 표, 줄 텍스트, KST 마감 표시."""

from datetime import date

from jarvis.core.tools.housing.fetch import kst_today
from jarvis.core.tools.housing.markup import deadline_label, lines_of, parse_date, table_rows, text_of

TODAY = date(2026, 10, 13)


def test_deadline_label_boundaries():
    assert deadline_label(date(2026, 10, 12), TODAY) == "마감됨"
    assert deadline_label(TODAY, TODAY) == "오늘 마감"
    assert deadline_label(date(2026, 10, 14), TODAY) == "D-1"
    assert deadline_label(None, TODAY) == "마감일 없음"


def test_parse_date_accepts_board_formats():
    assert parse_date("2026.10.26") == date(2026, 10, 26)
    assert parse_date("마감 2026-1-5 17:00") == date(2026, 1, 5)
    assert parse_date("") is None
    assert parse_date("2026.13.40") is None


def test_comments_and_scripts_are_not_text():
    raw = "<p>보임</p><!-- <p>옛 마크업</p> --><script>var x = '숨김';</script>"
    assert text_of(raw) == "보임"
    assert lines_of("<li>하나</li><li>둘 &amp; 셋</li>") == ["하나", "둘 & 셋"]


def test_table_rows_keeps_header_and_cells():
    rows = table_rows("<tr><th>주택형</th><th>가격</th></tr><tr><th>55A</th><td>504,484,000</td></tr>")
    assert rows == [["주택형", "가격"], ["55A", "504,484,000"]]


def test_kst_today_is_a_date():
    assert isinstance(kst_today(), date)
