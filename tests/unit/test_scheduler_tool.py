"""scheduler 의 schedule 도구: 말로 한 예약이 /schedule 과 같은 일정이 되고, 실패는 오류로 돌아간다."""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from jarvis.core.slash.schedule_cmd import make_schedule_handler
from jarvis.core.scheduler.tool import ScheduleTool
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="local", agent_id="main")


async def test_spoken_request_registers_a_once_reminder_for_the_calling_agent():
    scheduler = MagicMock()
    tool = ScheduleTool(make_schedule_handler(scheduler))

    out = await tool.execute("c1", {"request": "1분 뒤에 푸시 테스트"}, None, SimpleNamespace(scope=SCOPE))

    task = scheduler.add_task.call_args[0][0]
    assert (task.prompt, task.kind, task.agent) == ("푸시 테스트", "reminder", "main")
    assert out.is_error is False and "등록 완료" in out.content[0].text


@pytest.mark.parametrize(
    ("request_text", "context"),
    [("언젠가 알려줘", SimpleNamespace(scope=SCOPE)), ("1분 뒤에 x", None)],
    ids=["unparsable", "no_scope"],
)
async def test_invalid_request_is_an_error_and_registers_nothing(request_text, context):
    scheduler = MagicMock()
    tool = ScheduleTool(make_schedule_handler(scheduler))

    args = ("c1", {"request": request_text}) if context is None else ("c1", {"request": request_text}, None, context)
    out = await tool.execute(*args)

    assert out.is_error is True
    scheduler.add_task.assert_not_called()
