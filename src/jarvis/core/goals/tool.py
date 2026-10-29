"""[core] 대화 중에 맡긴 목표를 기록하고 스케줄러에 차례를 거는 goal 도구(맡기기, 목록, 멈추기)."""

import re
import asyncio
from datetime import datetime
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from jarvis.core.goals.types import DEFAULT_SCHEDULE, Goal, goal_key
from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.registry import JarvisTool, ToolContext
from jarvis.core.scheduler.task import ScheduledTask
from jarvis.core.goals.store import GoalStore
from jarvis.memory.scope import MAIN_AGENT

if TYPE_CHECKING:
    from jarvis.core.scheduler.service import SchedulerService

GOAL_TOOL = "goal"
TOOL_DESCRIPTION = (
    "사용자가 계속 맡기는 일('앞으로 ~만 알려줘', '~ 나오면 알려줘', '~ 계속 챙겨줘')을 목표로 맡는다."
    " 맡으면 대화가 없는 동안에도 정해진 때마다 한 단계씩 진행하고, 목표가 알리라고 한 것만 대화로 알린다."
    " 한 번만 하면 되는 일이나 정한 시각의 알림은 이 도구가 아니라 schedule 이다."
    " 같은 목표를 다시 맡겨도 하나로 남는다. action: set(맡기기), list(목록), stop(멈추기)."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["set", "list", "stop"]},
        "text": {"type": "string", "description": "목표 문장. 사용자가 말한 그대로. set, stop 에 쓴다"},
        "schedule": {"type": "string", "description": f"진행할 때(cron). 비우면 {DEFAULT_SCHEDULE}(9~21시 매시)"},
    },
    "required": ["action"],
}


# 계속 챙길 일일 수 있는 말. 걸리면 goal 을 먼저 보라는 규칙을 그 턴에 붙인다(판단은 모델이 한다)
STANDING_RE = re.compile(
    r"앞으로|계속|매번|(?:만|나오면|생기면|올라오면|바뀌면|뜨면|있으면)\s*(?:알려|말해|챙겨)|챙겨\s*(?:줘|주세요|줄래)"
)
GOAL_RULE = (
    "[목표 맡기기] 이 말이 지금 한 번 찾아 달라는 것이 아니라 앞으로 계속 챙겨 알려 달라는 것('~만 알려줘',"
    " '~ 나오면 알려줘')이면, 도구로 바로 찾기 전에 goal(action=set, text=사용자가 말한 그대로)로 맡고 짧게 답한다."
    " 속생각의 선택지가 바로 찾기여도 이 규칙이 먼저다. 지금 한 번 묻는 말이면 goal 을 쓰지 않는다."
)


def standing_rule(text: str, tool_names: set[str]) -> str | None:
    """이 턴에 붙일 목표 규칙. goal 도구가 있고 계속 챙길 일일 수 있는 말일 때만. 순수 함수.

    속생각이 '바로 찾아 전달' 을 선택지로 내면 KAREN 이 goal 대신 바로 찾았다(라이브 10번 중 0번 맡음).
    """
    return GOAL_RULE if GOAL_TOOL in tool_names and STANDING_RE.search(text) else None


def goal_task(goal: Goal) -> ScheduledTask:
    """목표의 차례를 거는 스케줄 작업. 이름이 목표 id 에서 나와 두 번 걸어도 하나다."""
    return ScheduledTask(
        name=goal.task_name,
        schedule=goal.schedule,
        prompt=goal.text,
        kind="goal",
        args={"goal": goal.id},
        agent=goal.agent,
        deliver="conversation",
        description=f"목표: {goal.text[:60]}",
        enabled=goal.status == "active",
    )


class GoalTool(JarvisTool):
    name = GOAL_TOOL
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "sequential"

    def __init__(
        self, store: GoalStore, scheduler: "SchedulerService", now: Callable[[], datetime] = datetime.now
    ) -> None:
        self._store = store
        self._scheduler = scheduler
        self._now = now

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        scope = getattr(context, "scope", None)
        agent = scope.agent_id if scope is not None else MAIN_AGENT
        action = str(params.get("action") or "")
        text = " ".join(str(params.get("text") or "").split())
        if action == "list":
            return _result(tool_call_id, self.list_goals(agent))
        if not text:
            return _result(tool_call_id, "목표 문장(text)이 필요하다", True)
        if action == "set":
            return _result(tool_call_id, self.set_goal(agent, text, str(params.get("schedule") or DEFAULT_SCHEDULE)))
        if action == "stop":
            return _result(tool_call_id, self.stop_goal(agent, text))
        return _result(tool_call_id, f"모르는 action: {action}", True)

    def set_goal(self, agent: str, text: str, schedule: str = DEFAULT_SCHEDULE) -> str:
        now_ms = int(self._now().timestamp() * 1000)
        goal = Goal(id=goal_key(agent, text), agent=agent, text=text, schedule=schedule,
                    created_at=now_ms, updated_at=now_ms)
        goal, created = self._store.ensure(goal)
        task = goal_task(goal)
        self._scheduler.ensure_task(task)
        if not created:
            return (
                f"이미 맡은 목표다(진행 {goal.runs}차례): {goal.text}."
                " 이번 답에서는 다른 도구를 부르지 말고 그렇다고만 답한다"
            )
        # 다음 정시를 기다리지 않고 첫 차례를 바로 돈다
        self._scheduler.run_soon(task)
        # 첫 차례가 따로 돌아 대화로 알린다. 이 턴에서 같은 일을 또 하면 지어낸 조건으로 도는 일이 있었다(실측)
        return (
            f"목표를 맡았다: {goal.text}. 첫 차례는 지금 따로 돌아 대화로 알리고, 그다음은 {schedule} 때마다 진행한다."
            " 이번 답에서는 다른 도구를 부르지 말고 맡았다고만 짧게 답한다"
        )

    def stop_goal(self, agent: str, text: str) -> str:
        goal = self._store.get(goal_key(agent, text)) or next(
            (g for g in self._store.list(agent) if g.status == "active" and text in g.text), None
        )
        if goal is None:
            return f"맡은 목표 중에 없다: {text}"
        self._store.save(goal.model_copy(update={"status": "paused"}))
        self._scheduler.set_enabled(goal.task_name, False)
        return f"목표를 멈췄다: {goal.text}"

    def list_goals(self, agent: str) -> str:
        goals = self._store.list(agent)
        if not goals:
            return "맡은 목표가 없다"
        return "\n".join(f"- [{g.status}] {g.text} (진행 {g.runs}차례, 알린 항목 {len(g.reported)}개)" for g in goals)


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=GOAL_TOOL, content=[TextContent(text=text)], is_error=is_error
    )
