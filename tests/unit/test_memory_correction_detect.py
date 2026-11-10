"""memory: 사용자 발화가 기억된 사실을 바로잡는 말인지 가리는 규칙을 검증."""

import pytest

from jarvis.memory.long_term.correction_detect import is_correction


@pytest.mark.parametrize("text", [
    "아니, 나 이제 부산 살아", "그게 아니라 5월이야", "그건 틀렸어", "Actually I moved to Busan", "No, it's Tuesday",
    "이제는 커피 안 마셔",
])
def test_correction_phrases_are_detected(text):
    assert is_correction(text)


@pytest.mark.parametrize("text", ["내일 날씨 어때?", "부산 맛집 알려줘", "Can you book a table?", ""])
def test_plain_requests_are_not_corrections(text):
    assert not is_correction(text)
