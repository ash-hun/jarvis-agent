"""goal 테스트 공용: 맡긴 목표 문장, 모델 답 꼴, 결과를 돌려주는 가짜 도구, 목표 저장소와 스케줄러 준비."""

import asyncio
from typing import Any
from datetime import datetime
from unittest.mock import MagicMock

from jarvis.core.tools.tools_registry import JarvisTool, ToolContext, ToolRegistry
from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.scheduler.scheduler_service import SchedulerService
from jarvis.core.goals.goals_types import Goal, goal_key
from jarvis.core.goals.goals_store import GoalStore
from jarvis.core.goals.runner import GoalRunner

NOW = datetime(2026, 10, 28, 10, 0)
TEXT = "조건 및 가장 좋은 원리금 납부액을 추천하는 공고만 알려줘"
HEAD = "애쉬, 조건에 맞고 월 부담이 가장 적은 공고예요."
REPLY = f"머리: {HEAD}\n항목: [2026:55A] 서울 행복주택, 55A 월 부담 최대 30만원\n기록: 1순위 확인\n완료: 아니오"
SAID = f"{HEAD}\n서울 행복주택, 55A 월 부담 최대 30만원"


class Final(JarvisTool):
    """부르면 '결과' 를 final 로 돌려주는 도구."""

    def __init__(self, name: str) -> None:
        self.name, self.description, self.parameters = name, name, {"type": "object"}

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: asyncio.Event | None = None,
                      context: ToolContext | None = None) -> ToolResultMessage:
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name,
                                 content=[TextContent(text="결과")], final=True)


def registry(*names: str) -> ToolRegistry:
    r = ToolRegistry()
    for n in names:
        r.register(Final(n))
    return r


def goal_setup(tmp_path) -> tuple[GoalStore, GoalRunner, Goal]:  # type: ignore[no-untyped-def]
    store = GoalStore(str(tmp_path))
    goal, _ = store.ensure(Goal(id=goal_key("karen", TEXT), agent="karen", text=TEXT))
    return store, GoalRunner(store, now=lambda: NOW), goal


def goal_scheduler() -> SchedulerService:
    return SchedulerService(tasks=[], session_repo=MagicMock(), tool_registry=registry("housing_budget"),
                            model=MagicMock())
