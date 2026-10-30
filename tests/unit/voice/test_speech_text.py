"""speech_text: 마크다운 기호를 지우고 읽을 글자만 남기는지."""

import pytest

from jarvis.voice.speech_text import speech_text

REPLY = """### 다음 주 회의 아젠다

#### 1. 개회 (5분)
- **참석자** 인사와 _역할_ 소개
* [회의 가이드](https://example.com/guide) 의 `agenda_v2` 를 따른다
> 지난 회의 요약

| 항목 | 시간 |
|---|---|
| 개회 | 5분 |

```python
print("skip")
```
---
자세한 건 https://example.com 참고. ~~취소~~ ***중요***"""


def test_markdown_symbols_are_not_read():
    spoken = speech_text(REPLY)
    for symbol in ("#", "**", "`", "|", "---", "](", "> ", "~~", "- "):
        assert symbol not in spoken


def test_words_survive():
    spoken = speech_text(REPLY)
    assert [line for line in spoken.splitlines() if line][:5] == [
        "다음 주 회의 아젠다",
        "1. 개회 (5분)",
        "참석자 인사와 역할 소개",
        "회의 가이드 의 agenda_v2 를 따른다",
        "지난 회의 요약",
    ]
    assert "항목, 시간" in spoken and "개회, 5분" in spoken
    assert "취소" in spoken and "중요" in spoken


def test_code_blocks_and_urls_are_dropped():
    spoken = speech_text(REPLY)
    assert "print" not in spoken
    assert "http" not in spoken


@pytest.mark.parametrize("text", ["snake_case_name 을 쓴다", "2*3*4 는 24", "그냥 문장."])
def test_plain_text_is_kept(text):
    assert speech_text(text) == text


def test_twice_is_same_as_once():
    once = speech_text(REPLY)
    assert speech_text(once) == once


@pytest.mark.parametrize(("written", "spoken"), [
    ("보유 현금 70,000,000원", "보유 현금 칠천만원"),
    ("월 여유자금 1,500,000원", "월 여유자금 백오십만원"),
    ("현금이 1,870만원 모자라요", "현금이 천팔백칠십만원 모자라요"),
    ("분양가 325,400,000원", "분양가 삼억이천오백사십만원"),
    ("10,000원, 11,000원", "만원, 만천원"),
    ("150000000원", "일억오천만원"),
])
def test_money_is_read_in_korean(written, spoken):
    """TTS 가 '70,000,000원' 을 '칠십천천원' 으로 읽었다. 금액은 한글 읽기로 넘긴다."""
    assert speech_text(written) == spoken
    assert speech_text(speech_text(written)) == spoken


def test_numbers_without_a_money_unit_are_left_alone():
    for text in ("2026년 10월 30일", "1,305가구", "59.8000B 타입", "3개", "$70,000"):
        assert speech_text(text) == text
