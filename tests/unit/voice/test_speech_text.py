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
