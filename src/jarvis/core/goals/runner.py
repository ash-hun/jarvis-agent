"""[core] 목표 한 차례: 프롬프트를 짓고, 에이전트를 경계 안의 도구로 돌리고, 답을 읽어 알릴 말만 돌려준다."""

import time
import asyncio
from typing import Any
from datetime import datetime
from dataclasses import dataclass, replace
from collections.abc import Awaitable, Callable

from jarvis.core.goals.goals_types import (
    ASK_PREFIX, Goal, Step, advance, compose, fingerprint, mark_reported, new_items, parse_step, with_tool_items,
    worth_noting,
)
from jarvis.core.tools.tools_registry import JarvisTool, ToolContext, ToolRegistry
from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.goals.goals_store import GoalStore
from jarvis.common.logger import get_logger

# 프롬프트에 보이는 최근 진행 기록 수
SHOWN_NOTES = 5
# 도구 없이 답한 차례를 한 번 더 돌릴 때 붙이는 말
RECHECK = "\n[다시] 지난 차례 기록 없이, 도구로 지금 상태를 확인한 뒤 같은 꼴로 답합니다."

# (프롬프트, 고른 도구 레지스트리) -> 에이전트의 마지막 답. 실패면 None. 스케줄러가 세션을 만들어 돌린다
RunAgent = Callable[[str, Callable[[ToolRegistry], ToolRegistry]], Awaitable[str | None]]
# (도구 이름, 인자) -> 모델 없이 부른 결과 글. 도구가 없거나 오류면 None
Replay = Callable[[str, dict[str, Any]], Awaitable[str | None]]

PROMPT = """\
[목표] {text}
사용자가 보지 않는 동안 이 목표를 한 차례 진행합니다. 지금은 {now} 입니다.
[지금까지 진행]
{notes}
[경계]
- 혼자 해도 되는 도구: {auto}
- 먼저 물어야 하는 일: {ask}. 이번 차례에는 하지 않습니다. 꼭 필요하면 허락을 구하는 말을
  항목으로 씁니다(키는 {ask_prefix} 로 시작)
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


@dataclass(frozen=True)
class ToolRun:
    """차례 안에서 불린 도구 하나. params 는 사용자만 정할 값을 버린 뒤 실제로 넘긴 인자다."""

    name: str
    params: dict[str, Any]
    text: str
    error: bool = False


def build_prompt(goal: Goal, auto: list[str], ask: list[str], now: datetime, notes: bool = True) -> str:
    """한 차례 프롬프트. 같은 목표, 같은 도구, 같은 시각이면 같은 글이다. 순수 함수."""
    return PROMPT.format(
        text=goal.text,
        now=now.strftime("%Y-%m-%d %H:%M"),
        notes="\n".join(f"- {n}" for n in goal.notes[-SHOWN_NOTES:] if notes) or "- 없음",
        auto=", ".join(auto) or "없음",
        ask=", ".join(ask) or "없음",
        ask_prefix=ASK_PREFIX,
    )


class _StepTool(JarvisTool):
    """사람이 없는 차례의 도구. 목표 차례면 사용자만 정할 인자를 버리고, 결과로 답을 끝내지(final) 않게 한다.
    목표 차례는 결과를 받아 정해진 꼴로 답해야 한다."""

    def __init__(self, tool: JarvisTool, goal_turn: bool, calls: list[ToolRun] | None = None) -> None:
        self._tool = tool
        self._goal_turn = goal_turn
        self._calls = calls
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
        if self._calls is not None:
            text = "\n".join(c.text for c in result.content if isinstance(c, TextContent))
            self._calls.append(ToolRun(self.name, params, text, result.is_error))
        return result.model_copy(update={"final": False}) if self._goal_turn else result


def step_registry(
    base: ToolRegistry, exclude: tuple[str, ...], goal_turn: bool = True, calls: list[ToolRun] | None = None
) -> ToolRegistry:
    """사람이 없는 차례에 쓸 도구: 먼저 물어야 하는 도구를 뺀다.
    목표 차례면 사용자만 정할 인자를 버리고 final 도 끈다. 스케줄 작업(goal_turn=False)은 둘 다 그대로다.
    calls 를 주면 불린 도구와 결과 글을 거기 적는다."""
    registry = ToolRegistry()
    for tool in base.list_all():
        if tool.name not in exclude:
            registry.register(_StepTool(tool, goal_turn, calls))
    return registry


class GoalRunner:
    """목표 차례를 돌린다. 알릴 항목은 건넨 뒤(settle)에야 알린 것으로 적는다.
    대화도 알림도 실패하면 다음 차례에 다시 온다.

    # idempotent: 건넨 직후 settle 전에 죽으면 다음 차례에 같은 항목을 한 번 더 건넨다(놓치는 것보다 낫다),
    중복이 거슬리면 건네기 전에 키를 '보내는 중' 으로 적고 전달 결과로 확정한다
    """

    def __init__(self, store: GoalStore, now: Callable[[], datetime] = datetime.now) -> None:
        self._store = store
        self._now = now
        # 목표 id -> 이번 차례에 건넬 항목 키. settle 이 꺼내 적는다
        self._pending: dict[str, list[str]] = {}

    @property
    def store(self) -> GoalStore:
        return self._store

    async def step(
        self, goal_id: str, auto: list[str], ask: list[str], run: RunAgent, replay: Replay | None = None
    ) -> str:
        """한 차례 진행하고 알릴 말을 돌려준다. 알릴 것이 없거나, 이미 알렸거나, 실패하면 빈 글.
        replay 를 주면 지난 차례의 도구를 먼저 다시 불러, 결과가 글자 그대로 같으면 모델을 부르지 않는다."""
        goal = self._store.get(goal_id)
        if goal is None or goal.status != "active":
            return ""
        now = self._now()
        started = time.perf_counter()
        # ponytail: 결과가 바뀐 차례는 도구를 두 번 부른다(다시 부르기, 모델),
        # 도구가 비싸지면 다시 부른 결과를 모델에 넘긴다
        if replay is not None and await self._unchanged(goal, auto, replay):
            # 같은 결과면 모델의 판단도 같다. 매시 차례가 새로 알릴 것 없이 13,000 토큰, 32초씩 썼다(실측)
            self._store.save(advance(goal, Step(), [], int(now.timestamp() * 1000)))
            self._pending[goal.id] = []
            logger.info(
                f"[Goal] {goal.agent}/{goal.id} run={goal.runs + 1} skipped=unchanged"
                f" took={time.perf_counter() - started:.1f}s"
            )
            return ""
        exclude = tuple(ask)
        calls: list[ToolRun] = []
        prompt = build_prompt(goal, auto, ask, now)
        reply = await run(prompt, lambda base: step_registry(base, exclude, calls=calls))
        rechecked = reply is not None and bool(auto) and not calls
        if rechecked:
            # 도구 없이 기록만 보고 답하면 그사이 바뀐 조건을 못 본다. "현금을 몰라" 기록이 쌓인 뒤 현금을 저장해도
            # 5번 중 5번 다시 현금을 물었다(실측)
            # 다시 돌릴 때는 기록을 빼고 보인다. 기록을 남긴 채로는 도구를 불러 놓고도 기록대로 다시 물었다(실측)
            retry = build_prompt(goal, auto, ask, now, notes=False) + RECHECK
            reply = await run(retry, lambda base: step_registry(base, exclude, calls=calls))
        texts = [c.text for c in calls]
        step = with_tool_items(parse_step(reply) if reply is not None else Step(), texts)
        if not worth_noting(step, bool(calls)):
            step = replace(step, note="")
        # 알렸는지는 모델이 아니라 키로 가린다. 모델은 이미 알린 것을 거르다 새 것까지 빼거나 엉뚱한 것을 물었다(실측)
        fresh = new_items(goal, step)
        report = compose(step, fresh)
        # 실패한 차례(답 없음, 도구 오류)는 지문을 남기지 않는다. 남기면 다음 차례가 그 실패를 그대로 건너뛴다
        clean = reply is not None and bool(calls) and not any(c.error for c in calls)
        remembered = {
            "last_calls": [{"name": c.name, "params": c.params} for c in calls] if clean else [],
            "seen": fingerprint(texts) if clean else "",
        }
        self._store.save(advance(goal, step, [], int(now.timestamp() * 1000)).model_copy(update=remembered))
        self._pending[goal.id] = [k for k, _ in fresh] if report else []
        # 평가 지표: 꼴을 지켰는지, 항목 수, 새로 알린 수, 키 없이 와 버린 수, 걸린 시간
        logger.info(
            f"[Goal] {goal.agent}/{goal.id} run={goal.runs + 1} parsed={step.parsed} items={len(step.items)}"
            f" new={len(fresh)} keyless={step.keyless} done={step.done} rechecked={rechecked}"
            f" took={time.perf_counter() - started:.1f}s"
        )
        return report

    def settle(self, goal_id: str, delivered: bool) -> None:
        """이번 차례의 항목을 건넸으면 알린 것으로 적고, 못 건넸으면 버려 다음 차례에 다시 알리게 한다."""
        keys = self._pending.pop(goal_id, [])
        goal = self._store.get(goal_id)
        if not keys or goal is None:
            return
        if delivered:
            self._store.save(mark_reported(goal, keys, int(self._now().timestamp() * 1000)))
        else:
            # 결과가 그대로여도 다음 차례에 모델이 다시 돌아 못 건넨 항목을 다시 알리게 지문을 지운다
            self._store.save(goal.model_copy(update={"seen": ""}))

    async def _unchanged(self, goal: Goal, auto: list[str], replay: Replay) -> bool:
        """지난 차례의 도구를 같은 인자로 다시 불러 결과 지문이 같은지. 지금 쓸 수 없는 도구가 있거나 오류면 False."""
        if not goal.seen or not goal.last_calls or any(c["name"] not in auto for c in goal.last_calls):
            return False
        results = [await replay(c["name"], dict(c["params"])) for c in goal.last_calls]
        if any(r is None for r in results):
            return False
        return fingerprint([r for r in results if r is not None]) == goal.seen
