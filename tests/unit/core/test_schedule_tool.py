"""schedule 도구: 말로 한 예약이 /schedule 과 같은 일정이 되고, 실패는 오류로 돌아간다."""

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


async def test_unparsable_request_is_an_error_and_registers_nothing():
    scheduler = MagicMock()
    tool = ScheduleTool(make_schedule_handler(scheduler))
    out = await tool.execute("c1", {"request": "언젠가 알려줘"}, None, SimpleNamespace(scope=SCOPE))
    assert out.is_error is True
    scheduler.add_task.assert_not_called()


async def test_without_scope_nothing_is_registered():
    scheduler = MagicMock()
    out = await ScheduleTool(make_schedule_handler(scheduler)).execute("c1", {"request": "1분 뒤에 x"})
    assert out.is_error is True
    scheduler.add_task.assert_not_called()
