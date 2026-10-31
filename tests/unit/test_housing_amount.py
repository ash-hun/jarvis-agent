"""housing: amount 가 사용자가 말한 한국어 금액을 원 단위 정수로 읽는지 검증."""

import pytest

from jarvis.core.tools.housing.amount import parse_won


@pytest.mark.parametrize(
    ("text", "won"),
    [
        ("1억 5천", 150_000_000),
        ("약 1억 5천", 150_000_000),
        ("1억5000만", 150_000_000),
        ("1억 2000", 120_000_000),
        ("1.5억", 150_000_000),
        ("6000만", 60_000_000),
        ("6천만원", 60_000_000),
        ("200만원", 2_000_000),
        ("2억 4천만 원", 240_000_000),
        ("150,000,000", 150_000_000),
        ("5천원", 5_000),
        ("3억 안쪽", 300_000_000),
        ("200만원 이하", 2_000_000),
        ("약 1억 5천 정도", 150_000_000),
        (150_000_000, 150_000_000),
        (2e6, 2_000_000),
    ],
)
def test_parse_won_reads_spoken_amounts(text, won):
    assert parse_won(text) == won


@pytest.mark.parametrize("text", ["", "abc", "억", "1억 abc", True])
def test_parse_won_rejects_unreadable_amounts(text):
    with pytest.raises(ValueError):
        parse_won(text)
