"""[core] 스케줄 루프. 때가 된 cron 작업과 한 번 실행 작업을 새 세션에서 돌리고 결과를 알린다."""

import uuid
import asyncio
from datetime import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from collections.abc import Awaitable, Callable, Coroutine

from jarvis.memory.scope import LOCAL_USER, MAIN_AGENT, MemoryScope
from jarvis.core.scheduler.task import ScheduledTask, task_label
from jarvis.core.scheduler.tool import SCHEDULE_TOOL
from jarvis.core.goals.tool import GOAL_TOOL
from jarvis.common.logger import get_logger

if TYPE_CHECKING:
    from jarvis.agent_layer.session.session_protocol import SessionRepo
    from jarvis.core.skills.skills_registry import SkillRegistry
    from jarvis.core.tools.tools_registry import ToolRegistry
    from jarvis.model_layer.model_types import ModelConfig
    from jarvis.core.plugins.runner import PluginRunner
    from jarvis.core.goals.runner import GoalRunner


# 실행 결과(알림)를 받아 화면에 전달하는 콜백. web 서버가 열린 HUD 로 방송한다.
Notify = Callable[[dict[str, Any]], Awaitable[None]]
# (에이전트 id, 말) -> 그 에이전트의 대화 세션에 건넸는가. 못 건넸으면 스케줄 알림으로 보낸다
Converse = Callable[[str, str], Awaitable[bool]]

# 목표 차례가 하지 않는 일: 새 목표와 새 일정 만들기. 목표가 스스로 일을 불리지 않게 한다
GOAL_TURN_EXCLUDED = (GOAL_TOOL, SCHEDULE_TOOL)
# 루프 주기. 한 번 실행(run_at) 알림이 이만큼까지 늦을 수 있다.
TICK_SEC = 10


@dataclass(frozen=True)
class TaskAgent:
    """main 이 아닌 에이전트로 작업을 돌릴 때 쓰는 것. 조립 층이 에이전트 정의에서 만들어 준다."""

    model: "ModelConfig"
    system_prompt: str | None
    agent_name: str
    # 그 에이전트 정의가 고른 도구. None 이면 스케줄러의 레지스트리(main 의 도구)를 쓴다
    tools: "ToolRegistry | None" = None
    # 경계의 "먼저 물어야 하는 일". 사람이 없는 작업과 목표 차례에서는 쓰지 않는다
    ask_tools: tuple[str, ...] = ()


# 에이전트 id → TaskAgent. 모르는 id 면 None
AgentResolver = Callable[[str], "TaskAgent | None"]

logger = get_logger(__name__)


class SchedulerService:
    """스케줄 루프. cron 반복 작업(croniter)과 정한 시각 한 번 실행(run_at) 작업.

    - 각 작업은 PermissiveSandbox + 필터된 ToolRegistry로 실행
    - HITL approval 없이 자율 실행
    - 결과는 notify 콜백으로 전달한다(설정돼 있을 때)
    """

    def __init__(
        self,
        tasks: list[ScheduledTask],
        session_repo: "SessionRepo",
        tool_registry: "ToolRegistry",
        model: "ModelConfig",
        schedules_dir: str | None = None,
        plugin_runner: "PluginRunner | None" = None,
        skill_registry: "SkillRegistry | None" = None,
    ) -> None:
        self._tasks = tasks
        # 설정되면 새 작업·토글을 이 디렉토리의 YAML 로 저장해 재시작 후에도 남긴다.
        self._schedules_dir = schedules_dir
        self._session_repo = session_repo
        self._tool_registry = tool_registry
        self._model = model
        # 주지 않으면 빈 것으로 둔다. None 을 세션에 넘기면 훅 호출에서 작업이 실패한다
        from jarvis.core.skills.skills_registry import SkillRegistry
        from jarvis.core.plugins.runner import PluginRunner

        self._plugin_runner = plugin_runner if plugin_runner is not None else PluginRunner()
        self._skill_registry = skill_registry if skill_registry is not None else SkillRegistry()
        self._running = False
        self._task_handle: asyncio.Task[None] | None = None
        self._notify: Notify | None = None
        self._converse: Converse | None = None
        self._agent_resolver: AgentResolver | None = None
        self._goals: GoalRunner | None = None
        self._last_run: dict[str, datetime] = {}  # cron 작업별 마지막으로 실행한 cron 슬롯
        self._bg: set[asyncio.Task[None]] = set()

    def set_agent_resolver(self, resolver: AgentResolver | None) -> None:
        """main 이 아닌 작업의 에이전트를 찾는 함수. 에이전트 레지스트리를 만든 뒤 조립 층이 단다."""
        self._agent_resolver = resolver

    def set_goal_runner(self, runner: "GoalRunner | None") -> None:
        """kind: goal 작업을 진행할 러너. 조립 층이 단다."""
        self._goals = runner

    def ensure_task(self, task: ScheduledTask) -> None:
        """같은 이름의 작업이 있으면 바꿔 끼우고 없으면 더한다. 두 번 불러도 작업은 하나다."""
        existing = self.get_task(task.name)
        if existing is not None:
            self._tasks.remove(existing)
            task._source = existing._source
        self.add_task(task)

    def run_soon(self, task: ScheduledTask) -> None:
        """다음 때를 기다리지 않고 지금 한 번 돌린다(목표를 맡긴 직후 첫 차례)."""
        self._spawn(self._run_and_deliver(task))

    def set_notifier(self, notify: Notify | None) -> None:
        """실행 결과를 받을 콜백을 단다. web 서버가 기동할 때 연결한다."""
        self._notify = notify

    def set_conversation(self, converse: Converse | None) -> None:
        """deliver: conversation 작업의 결과를 에이전트의 대화로 건넬 함수. web 서버가 기동할 때 연결한다."""
        self._converse = converse

    @property
    def task_count(self) -> int:
        return len([t for t in self._tasks if t.enabled])

    def add_task(self, task: ScheduledTask) -> None:
        self._tasks.append(task)
        if self._schedules_dir:
            from jarvis.core.scheduler.scheduler_loader import save_task

            save_task(task, self._schedules_dir)

    def list_tasks(self) -> list[ScheduledTask]:
        """등록된 작업 전부(꺼진 것 포함). 호출부가 목록을 바꿔도 내부 상태는 안전하다."""
        return list(self._tasks)

    def get_task(self, name: str) -> ScheduledTask | None:
        return next((t for t in self._tasks if t.name == name), None)

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """작업을 켜거나 끈다. 파일에서 온 작업이면 원본 YAML 에도 반영한다. 없는 이름이면 False."""
        task = self.get_task(name)
        if task is None:
            return False
        task.enabled = enabled
        if task._source is not None:
            from jarvis.core.scheduler.scheduler_loader import write_enabled

            write_enabled(task)
        elif self._schedules_dir:
            from jarvis.core.scheduler.scheduler_loader import save_task

            save_task(task, self._schedules_dir)
        return True

    @staticmethod
    def next_run(task: ScheduledTask, now: datetime | None = None) -> datetime | None:
        """다음 실행 시각. 꺼졌거나, 마감(run_until) 이후이거나, cron 을 못 읽으면 None."""
        if not task.enabled:
            return None
        if task.run_at is not None:
            return task.run_at
        try:
            from croniter import croniter
        except ImportError:
            return None
        now = now or datetime.now()
        try:
            nxt: datetime = croniter(task.schedule, now).get_next(datetime)
        except Exception:
            return None
        if task.run_until is not None and nxt > task.run_until:
            return None
        return nxt

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task_handle = asyncio.create_task(self._loop())
        logger.info(f"[Scheduler] Started with {self.task_count} enabled task(s)")

    async def stop(self) -> None:
        import contextlib
        self._running = False
        if self._task_handle:
            self._task_handle.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task_handle
        logger.info("[Scheduler] Stopped")

    async def _loop(self) -> None:
        try:
            from croniter import croniter
        except ImportError:
            croniter = None
            logger.info(
                "[Scheduler] croniter not installed — cron tasks disabled (one-shot still run). "
                "Run: uv sync --extra scheduler"
            )

        while self._running:
            try:
                self._tick(datetime.now(), croniter)
            except Exception as exc:
                # 작업 하나의 잘못으로 다른 작업(새 공고 감시 등)까지 멈추지 않게 한다
                logger.warning(f"[Scheduler] tick failed: {exc!r}")
            await asyncio.sleep(TICK_SEC)

    def _tick(self, now_dt: datetime, croniter: Any) -> list[asyncio.Task[None]]:
        """한 번 훑어 때가 된 작업을 띄운다. 띄운 백그라운드 task 목록을 돌려준다."""
        fired: list[asyncio.Task[None]] = []
        for task in list(self._tasks):
            if not task.enabled:
                continue

            # 정한 시각 한 번. 서버가 꺼져 있어 지난 것도 켜지는 즉시 보낸다(지연 초 표시)
            if task.run_at is not None:
                if now_dt >= task.run_at:
                    delay = int((now_dt - task.run_at).total_seconds())
                    self._retire(task)
                    fired.append(self._spawn(self._fire_once(task, delay)))
                continue

            # 마감 시각이 지난 슬래시 명령 작업은 자동 만료
            if task.run_until is not None and now_dt >= task.run_until:
                # 저장 파일에도 꺼 둔다. 메모리에서만 끄면 재시작 때 다시 켜진다
                self.set_enabled(task.name, False)
                logger.info(f"[Scheduler] Task '{task.name}' expired (run_until={task.run_until})")
                continue
            if croniter is None or not task.schedule:
                continue
            # datetime 으로 넘겨야 로컬 시간대로 해석된다. float epoch 를 주면 croniter 가 UTC 로 계산해
            # "매일 9시"가 18시(KST)에 뜬다.
            try:
                prev: datetime = croniter(task.schedule, now_dt).get_prev(datetime)
            except Exception as exc:
                logger.info(f"[Scheduler] Cron parse error for '{task.name}': {exc}")
                continue
            # 직전 cron 슬롯이 최근 60초 안이고 그 슬롯을 아직 안 돌았으면 실행
            if (now_dt - prev).total_seconds() < 60 and self._last_run.get(task.name) != prev:
                self._last_run[task.name] = prev
                fired.append(self._spawn(self._run_and_deliver(task)))
        return fired

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        t = asyncio.create_task(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)
        t.add_done_callback(self._on_task_done)
        return t

    def _retire(self, task: ScheduledTask) -> None:
        """한 번 실행 작업을 목록과 저장 파일에서 내린다(두 번 울리지 않게 실행 전에)."""
        if task in self._tasks:
            self._tasks.remove(task)
        task.enabled = False
        from jarvis.core.scheduler.scheduler_loader import remove_task_file

        remove_task_file(task, self._schedules_dir)

    async def _fire_once(self, task: ScheduledTask, delay_sec: int) -> None:
        await self._run(task, delay_sec)

    async def _run_and_deliver(self, task: ScheduledTask) -> None:
        await self._run(task, 0)

    async def _run(self, task: ScheduledTask, delay_sec: int) -> None:
        text = await self._produce(task)
        delivered = await self._deliver(task, text, delay_sec)
        if task.kind == "goal" and self._goals is not None:
            # 목표 항목은 건넨 뒤에야 알린 것으로 적는다. 못 건넸으면 다음 차례에 다시 온다
            self._goals.settle(str(task.args.get("goal", "")), delivered)

    async def _produce(self, task: ScheduledTask) -> str | None:
        """알릴 글. 실패하면 None."""
        if task.kind == "reminder":
            return task.prompt
        if task.kind == "tool":
            return await self._execute_tool(task)
        if task.kind == "goal":
            return await self._execute_goal(task)
        return await self._execute_task(task)

    async def _deliver(self, task: ScheduledTask, text: str | None, delay_sec: int) -> bool:
        """결과를 대화(deliver: conversation)나 notify 로 보낸다. text 가 None 이면 실행 실패. 건넸으면 True."""
        if task.kind in ("tool", "goal") and text is not None and not text.strip():
            # 도구나 목표 차례가 알릴 것이 없다고 빈 글을 줬다(새 공고 없음, 이미 알림 등)
            logger.info(f"[Scheduler] Tool task '{task.name}' had nothing to report")
            return False
        if task.deliver == "conversation" and text is not None and self._converse is not None:
            try:
                if await self._converse(task.agent, text):
                    return True
            except Exception as exc:
                logger.info(f"[Scheduler] conversation delivery failed for '{task.name}': {exc!r}")
            logger.info(f"[Scheduler] '{task.name}' has no conversation to join, sent as a notice")
        # 대화로 건네는 데는 알림 채널이 필요 없다. 알림으로 보낼 때만 본다
        if self._notify is None:
            return False
        payload = {
            "type": "reminder",
            "id": uuid.uuid4().hex,
            "name": task.name,
            "label": task_label(task),  # 알림 제목. /schedule 이 붙인 이름(once-xxxx)은 보이지 않는다
            "kind": task.kind,
            "agent": task.agent,
            "once": task.run_at is not None,
            "title": (task.prompt or task_label(task))[:160],
            "text": text if text is not None else "실행에 실패했습니다.",
            "error": text is None,
            "delayed_sec": delay_sec,
            "fired_at": datetime.now().astimezone().isoformat(),
        }
        try:
            await self._notify(payload)
        except Exception as exc:
            logger.info(f"[Scheduler] notify failed for '{task.name}': {exc!r}")
            return False
        return text is not None

    def _on_task_done(self, future: asyncio.Task[None]) -> None:
        """fire-and-forget task의 예외가 소실되지 않도록 로깅."""
        if not future.cancelled() and (exc := future.exception()):
            logger.info(f"[Scheduler] Unhandled exception in background task: {exc!r}")

    async def _execute_goal(self, task: ScheduledTask) -> str | None:
        """목표 한 차례. 알릴 말(없으면 빈 글). 러너가 없으면 실패(None)."""
        if self._goals is None:
            logger.info(f"[Scheduler] Goal task '{task.name}' failed: no goal runner")
            return None
        resolved = self._resolve(task)
        ask = sorted({*(resolved.ask_tools if resolved is not None else ()), *GOAL_TURN_EXCLUDED})
        auto = sorted(t.name for t in self._registry_for(task, resolved).list_all() if t.name not in ask)

        async def run(prompt: str, pick: Callable[["ToolRegistry"], "ToolRegistry"]) -> str | None:
            return await self._execute_task(task.model_copy(update={"prompt": prompt}), pick)

        async def replay(name: str, params: dict[str, Any]) -> str | None:
            from jarvis.core.goals.runner import step_registry

            # 모델이 부를 때와 같은 도구 포장(사용자만 정할 값 버리기)을 거친다
            registry = step_registry(self._registry_for(task, resolved), tuple(ask))
            return await self._call_tool(task, registry, name, params)

        return await self._goals.step(str(task.args.get("goal", "")), auto, ask, run, replay)

    async def _execute_task(
        self, task: ScheduledTask, pick: "Callable[[ToolRegistry], ToolRegistry] | None" = None
    ) -> str | None:
        """작업 프롬프트를 새 세션에서 실행하고 최종 답을 돌려준다. 실패하면 None. pick 은 쓸 도구를 다시 고른다."""
        from jarvis.core.policy.authenticator import NoAuthAuthenticator
        from jarvis.core.policy.pipeline import SecurityPipeline
        from jarvis.core.policy.sandbox import PermissiveSandbox
        from jarvis.core.policy.policy import AllowAllPolicy
        from jarvis.core.session import AgentSession

        logger.info(f"[Scheduler] Executing task '{task.name}'")

        resolved = self._resolve(task)
        if task.agent != MAIN_AGENT and resolved is None:
            logger.info(f"[Scheduler] Task '{task.name}' failed: unknown agent '{task.agent}'")
            return None
        filtered = self._registry_for(task, resolved)
        if pick is not None:
            filtered = pick(filtered)
        else:
            # 사람이 없는 작업이라 물을 수 없다. 먼저 물어야 하는 도구는 빼고 돈다
            from jarvis.core.goals.runner import step_registry

            ask = resolved.ask_tools if resolved is not None else ()
            filtered = step_registry(filtered, ask, goal_turn=False)

        # PermissiveSandbox: auto-approve all (no HITL)
        from jarvis.core.policy.validator import DefaultInputValidator
        sandbox = PermissiveSandbox()
        pipeline = SecurityPipeline(
            validator=DefaultInputValidator(),
            authenticator=NoAuthAuthenticator(),
            policy=AllowAllPolicy(),
            sandbox=sandbox,
        )

        model, system_prompt, agent_name = self._model, None, None
        if resolved is not None:
            model, system_prompt, agent_name = resolved.model, resolved.system_prompt, resolved.agent_name

        session_id = task.session_id or f"sched-{task.name}-{uuid.uuid4().hex[:8]}"
        await self._session_repo.create(session_id=session_id, agent_id=task.agent)

        session = AgentSession(
            model=model,
            session_id=session_id,
            security_pipeline=pipeline,
            plugin_runner=self._plugin_runner,
            tool_registry=filtered,
            skill_registry=self._skill_registry,
            session_repo=self._session_repo,
            system_prompt=system_prompt,
            agent_name=agent_name,
        )

        try:
            result = await session.prompt(task.prompt)
            tokens_in, tokens_out = await self._turn_tokens(session_id)
            # 작업 한 번의 비용을 실제 기록으로 보려고 남긴다(모델 호출 전부의 합)
            logger.info(
                f"[Scheduler] Task '{task.name}' completed → session {session_id}"
                f" tokens in={tokens_in} out={tokens_out}"
            )
            return result.text() if result is not None else ""
        except Exception as exc:
            logger.info(f"[Scheduler] Task '{task.name}' failed: {exc}")
            return None

    async def _turn_tokens(self, session_id: str) -> tuple[int, int]:
        from jarvis.model_layer.model_types import AssistantMessage

        try:
            messages = await self._session_repo.get_messages(session_id)
        except Exception:  # 비용 기록이 실패해도 작업 결과는 돌려준다
            return 0, 0
        replies = [m for m in messages if isinstance(m, AssistantMessage)]
        return sum(m.usage.input for m in replies), sum(m.usage.output for m in replies)

    def _resolve(self, task: ScheduledTask) -> TaskAgent | None:
        if task.agent == MAIN_AGENT or self._agent_resolver is None:
            return None
        return self._agent_resolver(task.agent)

    def _registry_for(self, task: ScheduledTask, resolved: TaskAgent | None) -> "ToolRegistry":
        """그 에이전트의 도구에서 tools_allowed 만 고른 레지스트리(비어 있으면 전부)."""
        base = resolved.tools if resolved is not None and resolved.tools is not None else self._tool_registry
        if not task.tools_allowed:
            return base
        from jarvis.core.tools.tools_registry import ToolRegistry

        filtered = ToolRegistry()
        for name in task.tools_allowed:
            tool = base.get(name)
            if tool:
                filtered.register(tool)
        return filtered

    async def _execute_tool(self, task: ScheduledTask) -> str | None:
        """task.tool 을 task.args 로 바로 부른 글. 도구가 없거나 오류면 None."""
        resolved = self._resolve(task)
        if task.agent != MAIN_AGENT and resolved is None:
            logger.info(f"[Scheduler] Tool task '{task.name}' failed: unknown agent '{task.agent}'")
            return None
        registry = self._registry_for(task, resolved)
        if registry.get(task.tool) is None:
            logger.info(f"[Scheduler] Tool task '{task.name}' failed: unknown tool '{task.tool}'")
            return None
        return await self._call_tool(task, registry, task.tool, dict(task.args))

    async def _call_tool(
        self, task: ScheduledTask, registry: "ToolRegistry", name: str, params: dict[str, Any]
    ) -> str | None:
        """도구 하나를 사람 없이 부른 글. 오류면 None."""
        from jarvis.core.tools.tools_registry import ToolContext
        from jarvis.model_layer.model_types import TextContent

        call_id = f"sched-{task.name}"
        # 스케줄은 사람이 없는 실행이라 로컬 사용자의 범위로 부른다(대화 세션의 memory_scope 와 같은 기본값)
        context = ToolContext(scope=MemoryScope(user_id=LOCAL_USER, agent_id=task.agent), session_id=call_id)
        # 도구의 예외는 레지스트리가 오류 결과로 바꿔 준다
        result = await registry.execute(call_id, name, params, None, context)
        text = "\n".join(c.text for c in result.content if isinstance(c, TextContent))
        if result.is_error:
            logger.info(f"[Scheduler] Tool task '{task.name}' failed: {text[:200]}")
            return None
        return text
