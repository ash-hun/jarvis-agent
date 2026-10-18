"""[core] 공고 게시판 HTML 에서 태그를 걷어 텍스트, 표, 날짜를 꺼내는 순수 함수."""

import re
import html
from datetime import date

_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_SCRIPT_RE = re.compile(r"<(script|style)\b[^>]*>[\s\S]*?</\1>", re.IGNORECASE)
_BREAK_RE = re.compile(r"<(br|/p|/li|/tr|/div|/h\d)\b[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_ROW_RE = re.compile(r"<tr\b[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
_CELL_RE = re.compile(r"<t[hd]\b[^>]*>([\s\S]*?)</t[hd]>", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")


def without_noise(raw: str) -> str:
    """주석과 script, style 을 뺀다. 주석 안의 옛 마크업이 본문처럼 읽히지 않게 한다."""
    return _SCRIPT_RE.sub(" ", _COMMENT_RE.sub(" ", raw))


def text_of(raw: str) -> str:
    """한 줄 텍스트. 공백을 하나로 접는다."""
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", without_noise(raw)))).strip()


def lines_of(raw: str) -> list[str]:
    """블록 경계마다 줄을 나눈 텍스트. 빈 줄은 뺀다."""
    broken = _BREAK_RE.sub("\n", without_noise(raw))
    text = html.unescape(_TAG_RE.sub(" ", broken))
    return [line for line in (re.sub(r"[ \t\r\f\v]+", " ", part).strip() for part in text.split("\n")) if line]


def table_rows(table_html: str) -> list[list[str]]:
    """표의 행마다 칸 텍스트. 머리 행도 같은 모양으로 들어간다."""
    rows = []
    for row in _ROW_RE.findall(table_html):
        cells = [text_of(cell) for cell in _CELL_RE.findall(row)]
        if cells:
            rows.append(cells)
    return rows


def parse_date(text: str) -> date | None:
    """'2026.10.26', '2026-10-26' 같은 첫 날짜. 없거나 틀린 날짜면 None."""
    match = _DATE_RE.search(text or "")
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def deadline_label(close: date | None, today: date) -> str:
    """KST 오늘 기준 마감 표시. 마감일이 없으면 그렇다고 적는다."""
    if close is None:
        return "마감일 없음"
    days = (close - today).days
    if days < 0:
        return "마감됨"
    if days == 0:
        return "오늘 마감"
    return f"D-{days}"
