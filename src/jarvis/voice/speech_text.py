"""[voice] 마크다운 응답을 소리 내어 읽을 문장으로 바꾼다. 기호는 지우고 글자만 남긴다."""

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


def speech_text(markdown: str) -> str:
    """읽을 문장. 코드 블록과 URL 은 읽지 않고, 링크와 강조는 글자만 남긴다. 두 번 거쳐도 같다."""
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
    return _BLANK_LINES.sub("\n\n", text).strip()
