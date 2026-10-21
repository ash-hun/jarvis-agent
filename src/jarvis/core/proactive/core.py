"""[core] proactive 코어. 정책, 채널, push 를 한 객체가 소유하고 Dual-Channel 과 자율 발화를 조율한다."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from jarvis.core.proactive.policy import SILENT_REASON, DefaultProactivityPolicy, ProactivityPolicy
from jarvis.core.proactive.types import ProactiveDecision, ProactiveMessage
from jarvis.agent_layer.thought.types import ProactiveAction, ThoughtFrame
from jarvis.model_layer.types import AssistantMessage

# 메인 에이전트 턴 실행기(slow channel). 결과 메시지(or None)를 반환.
RunMain = Callable[[], Awaitable[AssistantMessage | None]]
# proactive 발화 운반(fast channel / push, B2). UI에 비동기 전달.
EmitProactive = Callable[[ProactiveMessage], Awaitable[None]]
# 저위험 자율 행동 실행기(E2). 실행 후 사람이 읽을 요약을 반환. 보안 게이트는 호출부 책임.
ExecuteActions = Callable[[list[ProactiveAction]], Awaitable[str]]


class ProactivityCore:
    """proactive 동작 코어의 기본 클래스. 정책, 채널, push 를 한 객체가 소유한다.

    독립 class로 격리되어 통째 교체 가능하다. 진입점 2개:
    - dispatch_request : 요청-기반 Dual-Channel (filler + 백그라운드 메인 루프)
    - reflect          : daemon 자율 발화 게이팅 + push (B3)
    기본 구현은 늘 메인 턴을 바로 돌리고 먼저 말하지 않는다(proactive 를 끈 세션과 같다).
    """

    async def dispatch_request(self, frame: ThoughtFrame | None, run_main: RunMain) -> AssistantMessage | None:
        return await run_main()

    async def reflect(
        self,
        frame: ThoughtFrame,
        *,
        session_id: str = "default",
        execute: ExecuteActions | None = None,
    ) -> ProactiveDecision:
        return ProactiveDecision(speak=False, reason=SILENT_REASON)

    def check_awaiting(self, session_id: str = "default") -> ProactiveDecision | None:
        return None

    def note_user_activity(self, session_id: str = "default") -> None:
        pass

    def restore_awaiting(self, session_id: str = "default") -> None:
        pass


class DefaultProactivityCore(ProactivityCore):
    """기본 Dual-Channel 오케스트레이터.

    협력자는 전부 생성자 주입(정책·push·spawn)이라 session/UI와 분리된다.
    - fast channel : emit_proactive(filler) 즉시 발화
    - slow channel : run_main()을 (지연 모드면) 백그라운드 task로 수행
    """

    def __init__(
        self,
        emit_proactive: EmitProactive,
        policy: ProactivityPolicy | None = None,
        spawn: Callable[[Awaitable[None]], None] | None = None,
    ) -> None:
        self._emit = emit_proactive
        self._policy = policy or DefaultProactivityPolicy()
        self._spawn = spawn or self._default_spawn
        self._bg_tasks: set[asyncio.Task[None]] = set()

    async def dispatch_request(self, frame: ThoughtFrame | None, run_main: RunMain) -> AssistantMessage | None:
        # 프레임이 없거나(사고 비활성) 즉시 모드면 현재 동작 그대로.
        if frame is None:
            return await run_main()

        plan = self._policy.plan_response(frame)
        if plan.mode == "immediate":
            return await run_main()

        # deferred. fast channel: filler 즉시 발화 → slow channel: 백그라운드 수행.
        await self._emit(ProactiveMessage(text=plan.filler, kind="filler"))
        self._spawn(self._run_deferred(run_main))
        return None

    async def reflect(
        self,
        frame: ThoughtFrame,
        *,
        session_id: str = "default",
        execute: ExecuteActions | None = None,
    ) -> ProactiveDecision:
        decision = self._policy.decide_proactive(frame, session_id=session_id)
        if not decision.speak:
            return decision

        # E2. 게이팅 통과 시 저위험 자율 행동을 먼저 실행(실행→알림) 후 요약을
        # 메시지에 덧붙인다. execute가 없으면 행동은 건너뛰고 메시지만 push.
        note = ""
        if execute is not None and decision.autonomous_actions:
            with contextlib.suppress(Exception):
                note = await execute(decision.autonomous_actions)

        text = decision.message
        if note:
            text = f"{text}\n{note}" if text else note
        if text:
            await self._emit(ProactiveMessage(text=text, kind="proactive"))
        return decision

    def check_awaiting(self, session_id: str = "default") -> ProactiveDecision | None:
        return self._policy.check_awaiting(session_id)

    def note_user_activity(self, session_id: str = "default") -> None:
        self._policy.note_user_activity(session_id)

    def restore_awaiting(self, session_id: str = "default") -> None:
        self._policy.restore_awaiting(session_id)

    async def _run_deferred(self, run_main: RunMain) -> None:
        # 메인 루프는 자체 이벤트(stream/agent_end)를 그대로 emit → 답은 그 경로로 전달.
        # 백그라운드 실패가 호출부를 깨지 않도록 격리.
        with contextlib.suppress(Exception):
            await run_main()

    def _default_spawn(self, coro: Awaitable[None]) -> None:
        # spawn 계약은 Awaitable 이지만 실제로 넘기는 것은 _run_deferred 코루틴이다
        task: asyncio.Task[None] = asyncio.create_task(coro)  # type: ignore[arg-type]
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
