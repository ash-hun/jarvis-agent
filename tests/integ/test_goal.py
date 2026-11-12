"""goal 기능: 정각 차례가 목표를 진행해 대화로 건네고, 결과가 같으면 침묵하고, 지나친 정각은 한 번만 따라잡는다."""

import pytest
import asyncio
from typing import Any
from unittest.mock import MagicMock
from datetime import datetime, timedelta

from jarvis.core.tools.tools_registry import JarvisTool, ToolContext, ToolRegistry
from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.scheduler.scheduler_service import SchedulerService
from tests.fixtures.goal_helpers import REPLY, SAID, goal_setup
from jarvis.core.scheduler.task import ScheduledTask
from jarvis.core.goals.tool import goal_task

croniter = pytest.importorskip("croniter").croniter

CHANGED_REPLY = REPLY.replace("[2026:55A] 서울 행복주택, 55A", "[2026:59B] 서울 행복주택, 59B").replace("30만원", "25만원")
CHANGED_SAID = SAID.replace("55A 월 부담 최대 30만원", "59B 월 부담 최대 25만원")


class Board(JarvisTool):
    """게시판 도구. text 를 바꾸면 결과가 바뀐 것이다."""

    name = "housing_budget"
    description = "x"
    parameters = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.text = "결과 1"

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: asyncio.Event | None = None,
                      context: ToolContext | None = None) -> ToolResultMessage:
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name,
                                 content=[TextContent(text=self.text)], final=True)


async def _tick(svc: SchedulerService, at: datetime) -> None:
    await asyncio.gather(*svc._tick(at, croniter))


async def test_goal_turns_report_once_stay_silent_on_same_result_and_catch_up_a_missed_hour(tmp_path):
    store, runner, goal = goal_setup(tmp_path)
    board = Board()
    tools = ToolRegistry()
    tools.register(board)
    svc = SchedulerService(tasks=[], session_repo=MagicMock(), tool_registry=tools, model=MagicMock())
    svc.set_goal_runner(runner)
    spoken: list[str] = []
    replies = [REPLY]

    async def converse(agent: str, text: str) -> bool:
        spoken.append(text)
        return True

    async def execute(task: ScheduledTask, pick: Any = None) -> str:
        await pick(tools).execute("c", board.name, {}, None, None)
        return replies.pop(0)

    svc.set_conversation(converse)
    svc._execute_task = execute  # type: ignore[method-assign]
    svc.add_task(goal_task(goal))
    day = datetime(2026, 11, 11)

    # 10시 정각: 첫 차례가 1순위를 대화로 건네고 알린 것으로 적는다
    await _tick(svc, day + timedelta(hours=10, seconds=5))
    assert spoken == [SAID] and store.get(goal.id).reported == ["2026:55A"]

    # 11시: 도구 결과가 그대로라 모델을 부르지 않고 조용하다
    await _tick(svc, day + timedelta(hours=11, seconds=5))
    assert spoken == [SAID] and replies == [] and store.get(goal.id).runs == 2

    # 12시, 13시 정각을 절전으로 지나친 뒤 14:01:30 에 깨어남: 가장 최근 정각 하나만 따라잡는다
    await _tick(svc, day + timedelta(hours=14, minutes=1, seconds=30))
    await _tick(svc, day + timedelta(hours=14, minutes=1, seconds=40))
    assert store.get(goal.id).runs == 3 and spoken == [SAID]

    # 15시: 게시판이 바뀌어 모델이 다시 돌고 새 1순위만 건넨다
    board.text, replies[:] = "결과 2", [CHANGED_REPLY]
    await _tick(svc, day + timedelta(hours=15, seconds=5))
    assert spoken == [SAID, CHANGED_SAID] and store.get(goal.id).reported == ["2026:55A", "2026:59B"]


async def test_goal_turn_failed_delivery_is_retried_next_hour(tmp_path):
    store, runner, goal = goal_setup(tmp_path)
    tools = ToolRegistry()
    tools.register(Board())
    svc = SchedulerService(tasks=[], session_repo=MagicMock(), tool_registry=tools, model=MagicMock())
    svc.set_goal_runner(runner)
    up = False
    spoken: list[str] = []

    async def converse(agent: str, text: str) -> bool:
        spoken.append(text)
        return up

    async def execute(task: ScheduledTask, pick: Any = None) -> str:
        await pick(tools).execute("c", "housing_budget", {}, None, None)
        return REPLY

    svc.set_conversation(converse)
    svc._execute_task = execute  # type: ignore[method-assign]
    svc.add_task(goal_task(goal))
    day = datetime(2026, 11, 11)

    await _tick(svc, day + timedelta(hours=10, seconds=5))
    assert spoken == [SAID] and store.get(goal.id).reported == []

    up = True
    await _tick(svc, day + timedelta(hours=11, seconds=5))
    assert spoken == [SAID, SAID] and store.get(goal.id).reported == ["2026:55A"]
