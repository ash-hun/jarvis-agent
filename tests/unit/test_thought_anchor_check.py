"""thought 의 anchor_check: 말이 근거 항목의 숫자, 이름, 핵심 낱말을 하나라도 담았는지 관대하게 본다."""

import pytest

from jarvis.agent_layer.thought.anchor_check import anchor_present, anchor_terms

ANCHOR = "[bank] 신한카드 결제대금 1,284,300원 자동이체 예정(오늘 10:00). 잔액으로 부족합니다."


def test_anchor_terms_drop_tag_commas_josa_and_stopwords() -> None:
    terms = anchor_terms(ANCHOR)

    assert "1284300" in terms and "10:00" in terms and "잔액" in terms
    assert "bank" not in terms and "오늘" not in terms


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("10시에 자동이체가 있는데 잔액이 모자라요", True),
        ("결제 금액 1,284,300원이 빠져나가요", True),
        ("신한 카드 결제가 곧이에요", True),
        ("안녕하세요! 더 궁금한 점 있으세요?", False),
        ("사용자는 쉬고 있는 것으로 보인다", False),
    ],
    ids=["hour_and_word", "number", "prefix", "greeting", "analysis"],
)
def test_anchor_present(utterance, expected) -> None:  # type: ignore[no-untyped-def]
    assert anchor_present(ANCHOR, utterance) is expected


def test_anchor_present_without_terms_does_not_block() -> None:
    assert anchor_present("[ci] 오늘", "아무 말") is True
