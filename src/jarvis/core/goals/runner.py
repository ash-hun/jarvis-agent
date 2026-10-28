"""[core] 목표 한 차례: 프롬프트를 짓고, 에이전트를 경계 안의 도구로 돌리고, 답을 읽어 알릴 말만 돌려준다."""

import time
import asyncio
from typing import Any
from datetime import datetime
from collections.abc import Awaitable, Callable

from jarvis.core.goals.types import Goal, Step, advance, compose, new_items, parse_step
from jarvis.core.tools.registry import JarvisTool, ToolContext, ToolRegistry
from jarvis.model_layer.types import ToolResultMessage
from jarvis.core.goals.store import GoalStore
from jarvis.common.logger import get_logger

# 프롬프트에 보이는 최근 진행 기록 수
SHOWN_NOTES = 5

# (프롬프트, 고른 도구 레지스트리) -> 에이전트의 마지막 답. 실패면 None. 스케줄러가 세션을 만들어 돌린다
RunAgent = Callable[[str, Callable[[ToolRegistry], ToolRegistry]], Awaitable[str | None]]

PROMPT = """\
[목표] {text}
사용자가 보지 않는 동안 이 목표를 한 차례 진행합니다. 지금은 {now} 입니다.
[지금까지 진행]
{notes}
[경계]
- 혼자 해도 되는 도구: {auto}
- 먼저 물어야 하는 일: {ask}. 이번 차례에는 하지 않습니다. 꼭 필요하면 허락을 구하는 말을 항목으로 씁니다
할 일:
- 목표를 위해 지금 할 다음 한 단계를 정해 도구로 합니다. 도구 결과로 확인한 사실만 씁니다.
- 목표가 알리라고 한 것을 지금 기준으로 모두 항목으로 씁니다. 전에 알렸는지는 따지지 않습니다.
  이미 알린 항목은 시스템이 거릅니다.
- 알릴 것이 없으면 항목을 쓰지 않습니다. "새 소식이 없어요" 같은 말은 항목이 아닙니다.
- 끝나면 아래 꼴로만 답합니다. 다른 말은 붙이지 않습니다.
머리: <항목 앞에 둘, 사용자에게 대화하듯 건넬 한 문장. 개수나 무엇이 바뀌었는지는 쓰지 않습니다. 없으면 없음>
항목: [<그것을 가리키는, 다음에도 바뀌지 않는 키>] <사용자에게 건넬 한 줄>
(항목은 알릴 것마다 한 줄씩 씁니다)
기록: <다음 차례를 위해 남길 진행 메모 한 줄>
완료: <목표를 다 이뤄 더 할 일이 없으면 예, 아니면 아니오>"""

logger = get_logger(__name__)


def build_prompt(goal: Goal, auto: list[str], ask: list[str], now: datetime) -> str:
    """한 차례 프롬프트. 같은 목표, 같은 도구, 같은 시각이면 같은 글이다. 순수 함수."""
    return PROMPT.format(
        text=goal.text,
        now=now.strftime("%Y-%m-%d %H:%M"),
        notes="\n".join(f"- {n}" for n in goal.notes[-SHOWN_NOTES:]) or "- 없음(첫 차례)",
        auto=", ".join(auto) or "없음",
        ask=", ".join(ask) or "없음",
    )


class _StepTool(JarvisTool):
    """사람이 없는 차례의 도구. 목표 차례면 사용자만 정할 인자를 버리고, 결과로 답을 끝내지(final) 않게 한다.
    목표 차례는 결과를 받아 정해진 꼴로 답해야 한다."""

    def __init__(self, tool: JarvisTool, goal_turn: bool) -> None:
        self._tool = tool
        self._goal_turn = goal_turn
        self.name = tool.name
        self.description = tool.description
        self.parameters = tool.parameters
        self.execution_mode = tool.execution_mode
        # 목표 문장에는 돈 같은 값이 없다. 스케줄 작업은 사용자가 쓴 지시에 값이 있을 수 있어 그대로 둔다
        self._user_only = getattr(tool, "user_only_params", ()) if goal_turn else ()

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        dropped = [k for k in params if k in self._user_only]
        if dropped:
            logger.info(f"[Goal] {self.name}: 사람이 없는 차례라 사용자만 정할 값을 버린다: {dropped}")
            params = {k: v for k, v in params.items() if k not in self._user_only}
        registry = ToolRegistry()
        registry.register(self._tool)
        result = await registry.execute(tool_call_id, self.name, params, signal, context)
        return result.model_copy(update={"final": False}) if self._goal_turn else result


def step_registry(base: ToolRegistry, exclude: tuple[str, ...], goal_turn: bool = True) -> ToolRegistry:
    """사람이 없는 차례에 쓸 도구: 먼저 물어야 하는 도구를 뺀다.
    목표 차례면 사용자만 정할 인자를 버리고 final 도 끈다. 스케줄 작업(goal_turn=False)은 둘 다 그대로다."""
    registry = ToolRegistry()
    for tool in base.list_all():
        if tool.name not in exclude:
            registry.register(_StepTool(tool, goal_turn))
    return registry


class GoalRunner:
    """# ponytail: 돌려준 보고는 알린 것으로 적는다(스케줄러는 대화가 없으면 알림으로 보낸다),
    알림 채널까지 실패해 놓치는 일이 보이면 전달 결과를 받아 적도록 바꾼다
    """

    def __init__(self, store: GoalStore, now: Callable[[], datetime] = datetime.now) -> None:
        self._store = store
        self._now = now

    @property
    def store(self) -> GoalStore:
        return self._store

    async def step(self, goal_id: str, auto: list[str], ask: list[str], run: RunAgent) -> str:
        """한 차례 진행하고 알릴 말을 돌려준다. 알릴 것이 없거나, 이미 알렸거나, 실패하면 빈 글."""
        goal = self._store.get(goal_id)
        if goal is None or goal.status != "active":
            return ""
        now = self._now()
        started = time.perf_counter()
        exclude = tuple(ask)
        reply = await run(build_prompt(goal, auto, ask, now), lambda base: step_registry(base, exclude))
        step = parse_step(reply) if reply is not None else Step()
        # 알렸는지는 모델이 아니라 키로 가린다. 모델은 이미 알린 것을 거르다 새 것까지 빼거나 엉뚱한 것을 물었다(실측)
        fresh = new_items(goal, step)
        report = compose(step, fresh)
        self._store.save(advance(goal, step, [k for k, _ in fresh], int(now.timestamp() * 1000)))
        # 평가 지표: 꼴을 지켰는지, 항목 수, 새로 알린 수, 키 없이 와 버린 수, 걸린 시간
        logger.info(
            f"[Goal] {goal.agent}/{goal.id} run={goal.runs + 1} parsed={step.parsed} items={len(step.items)}"
            f" new={len(fresh)} keyless={step.keyless} done={step.done} took={time.perf_counter() - started:.1f}s"
        )
        return report
