"""housing: markup 이 게시판 HTML 에서 날짜, 표, 줄 텍스트, KST 마감 표시를 뽑는지 검증."""

import pytest
from datetime import date

from jarvis.core.tools.housing.markup import deadline_label, lines_of, parse_date, table_rows, text_of

TODAY = date(2026, 10, 13)


@pytest.mark.parametrize(
    ("closes", "label"),
    [(date(2026, 10, 12), "마감됨"), (TODAY, "오늘 마감"), (date(2026, 10, 14), "D-1"), (None, "마감일 없음")],
)
def test_deadline_label_marks_boundaries(closes, label):
    assert deadline_label(closes, TODAY) == label


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2026.10.26", date(2026, 10, 26)), ("마감 2026-1-5 17:00", date(2026, 1, 5)), ("", None), ("2026.13.40", None)],
)
def test_parse_date_accepts_board_formats(text, expected):
    assert parse_date(text) == expected


def test_text_of_skips_comments_and_scripts():
    raw = "<p>보임</p><!-- <p>옛 마크업</p> --><script>var x = '숨김';</script>"

    assert text_of(raw) == "보임"
    assert lines_of("<li>하나</li><li>둘 &amp; 셋</li>") == ["하나", "둘 & 셋"]


def test_table_rows_keeps_header_and_cells():
    rows = table_rows("<tr><th>주택형</th><th>가격</th></tr><tr><th>55A</th><td>504,484,000</td></tr>")

    assert rows == [["주택형", "가격"], ["55A", "504,484,000"]]
