"""multi_agent: 감독자 지시문 설정값을 문자열 또는 파일에서 읽는지 검증한다."""

import pytest

from jarvis.core.multi_agent.multi_agent_service import load_supervisor_prompt


@pytest.mark.parametrize(("value", "expected"), [("", None), ("짧게 답하라", "짧게 답하라")])
def test_load_supervisor_prompt_uses_value_or_none_when_empty(value, expected):
    assert load_supervisor_prompt(value) == expected


def test_load_supervisor_prompt_reads_file_path(tmp_path):
    f = tmp_path / "sup.md"
    f.write_text("파일에서 읽은 지시문\n")

    assert load_supervisor_prompt(str(f)) == "파일에서 읽은 지시문"
