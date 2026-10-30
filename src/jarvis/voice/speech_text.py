"""[voice] 마크다운 응답을 소리 내어 읽을 문장으로 바꾼다. 기호는 지우고 글자만 남기고, 금액 숫자는 한글로 바꾼다."""

import re

_FENCED_CODE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"<?https?://\S+>?")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_TABLE_RULE = re.compile(r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*(?:\n|\Z)", re.MULTILINE)
_HORIZONTAL_RULE = re.compile(r"^[ \t]*(?:[-*_][ \t]*){3,}(?:\n|\Z)", re.MULTILINE)
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.MULTILINE)
_QUOTE = re.compile(r"^[ \t]*(?:>[ \t]?)+", re.MULTILINE)
_BULLET = re.compile(r"^[ \t]*[-*+][ \t]+(?:\[[ xX]\][ \t]+)?", re.MULTILINE)
# 단어 안의 밑줄(snake_case)과 곱셈 별표는 남긴다. 글자를 감싼 강조 기호만 지운다
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3}|~~)(?=\S)(.+?)(?<=\S)\1(?!\w)")
_INLINE_CODE = re.compile(r"`+([^`]*)`+")
_TABLE_PIPE = re.compile(r"\s*\|\s*")
_SPACES = re.compile(r"[ \t]{2,}")
_BLANK_LINES = re.compile(r"\n{3,}")
# 쉼표 묶음이나 다섯 자리 이상 숫자 뒤에 원, 만, 억이 오면 금액이다
# TTS 가 "70,000,000원" 을 "칠십천천원" 으로 읽었다(실측)
# 단위가 없는 숫자(연도, 개수)는 고유어로 읽어야 할 때가 있어 건드리지 않는다
_MONEY = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d{5,})(?![\d.,])(?=\s*(?:원|만|억))")
_DIGITS = "영일이삼사오육칠팔구"
_SMALL_UNITS = ("", "십", "백", "천")
_BIG_UNITS = ("", "만", "억", "조", "경")


def korean_number(n: int) -> str:
    """한자어 수 읽기. 10,000 은 '일만' 이 아니라 '만', 1,000 은 '천'. 순수 함수."""
    if n == 0:
        return _DIGITS[0]
    groups: list[str] = []
    for unit in _BIG_UNITS:
        n, group = divmod(n, 10_000)
        if group:
            digits = [int(c) for c in f"{group:04d}"]
            words = "".join(
                ("" if d == 1 and small else _DIGITS[d]) + small
                for d, small in zip(digits, reversed(_SMALL_UNITS), strict=True) if d
            )
            groups.append(("" if words == "일" and unit == "만" else words) + unit)
        if not n:
            break
    return "".join(reversed(groups))


def speech_text(markdown: str) -> str:
    """읽을 문장. 코드 블록과 URL 은 읽지 않고, 링크와 강조는 글자만 남기고, 금액 숫자는 한글로. 두 번 거쳐도 같다."""
    text = _FENCED_CODE.sub(" ", markdown)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _HTML_TAG.sub(" ", text)
    text = _TABLE_RULE.sub("", text)
    text = _HORIZONTAL_RULE.sub("", text)
    text = _HEADING.sub("", text)
    text = _QUOTE.sub("", text)
    text = _BULLET.sub("", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _EMPHASIS.sub(r"\2", text)
    lines = [_TABLE_PIPE.sub(", ", line).strip(" ,") if "|" in line else line for line in text.split("\n")]
    text = "\n".join(_SPACES.sub(" ", line).strip() for line in lines)
    text = _MONEY.sub(lambda m: korean_number(int(m.group(1).replace(",", ""))), text)
    return _BLANK_LINES.sub("\n\n", text).strip()
