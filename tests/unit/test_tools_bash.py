"""tools 의 bash 내장 도구: 명령 결과를 돌려주고 실패와 시간 초과를 오류로 알리는지 검증한다."""

import pytest

from jarvis.core.tools.builtin.bash import BashTool


async def test_bash_returns_command_output():
    result = await BashTool().execute("c1", {"command": "echo hello"})

    assert result.is_error is False
    assert "hello" in result.content[0].text


@pytest.mark.parametrize(
    ("params", "text"),
    [({"command": "exit 1"}, ""), ({"command": "sleep 10", "timeout": 1}, "timed out")],
)
async def test_bash_reports_failure_or_timeout_as_error(params, text):
    result = await BashTool().execute("c1", params)

    assert result.is_error is True
    assert text in result.content[0].text
