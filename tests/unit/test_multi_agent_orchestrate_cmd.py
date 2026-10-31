"""multi_agent: /orchestrate 인자 해석이 플래그 위치와 대소문자에 상관없고 작업이 없으면 거부하는지 검증한다."""

import pytest

from jarvis.core.slash.orchestrate_cmd import parse_args


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("blackboard --agents a,b --promote 시장 분석", ("blackboard", ["a", "b"], True, "시장 분석")),
        ("Market 날씨 알려줘", ("market", None, False, "날씨 알려줘")),
    ],
)
def test_parse_args_reads_pattern_flags_and_task(text, expected):
    assert parse_args(text) == expected


def test_parse_args_without_task_raises():
    with pytest.raises(ValueError):
        parse_args("market")
