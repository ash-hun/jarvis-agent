"""[core] 스케줄 루프. 때가 된 cron 작업과 한 번 실행 작업을 새 세션에서 돌리고 결과를 알린다."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import TYPE_CHECKING, Any

from jarvis.common.logger import get_logger
from jarvis.core.scheduler.task import ScheduledTask

if TYPE_CHECKING:
    from jarvis.agent_layer.session.protocol import SessionRepo
    from jarvis.core.plugins.runner import PluginRunner
    from jarvis.core.skills.registry import SkillRegistry
    from jarvis.core.tools.registry import ToolRegistry
    from jarvis.model_layer.types import ModelConfig


# 실행 결과(알림)를 받아 화면에 전달하는 콜백. web 서버가 열린 HUD 로 방송한다.
Notify = Callable[[dict[str, Any]], Awaitable[None]]

# 루프 주기. 한 번 실행(run_at) 알림이 이만큼까지 늦을 수 있다.
TICK_SEC = 10

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
        session_repo: SessionRepo,
        tool_registry: ToolRegistry,
        model: ModelConfig,
        schedules_dir: str | None = None,
        plugin_runner: PluginRunner | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self._tasks = tasks
        # 설정되면 새 작업·토글을 이 디렉토리의 YAML 로 저장해 재시작 후에도 남긴다.
        self._schedules_dir = schedules_dir
        self._session_repo = session_repo
        self._tool_registry = tool_registry
        self._model = model
        self._plugin_runner = plugin_runner
        self._skill_registry = skill_registry
        self._running = False
        self._task_handle: asyncio.Task[None] | None = None
        self._notify: Notify | None = None
        self._last_run: dict[str, datetime] = {}  # cron 작업별 마지막으로 실행한 cron 슬롯
        self._bg: set[asyncio.Task[None]] = set()

    def set_notifier(self, notify: Notify | None) -> None:
        """실행 결과를 받을 콜백을 단다. web 서버가 기동할 때 연결한다."""
        self._notify = notify

    @property
    def task_count(self) -> int:
        return len([t for t in self._tasks if t.enabled])

    def add_task(self, task: ScheduledTask) -> None:
        self._tasks.append(task)
        if self._schedules_dir:
            from jarvis.core.scheduler.loader import save_task

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
            from jarvis.core.scheduler.loader import write_enabled

            write_enabled(task)
        elif self._schedules_dir:
            from jarvis.core.scheduler.loader import save_task

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
            self._tick(datetime.now(), croniter)
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
                task.enabled = False
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
        from jarvis.core.scheduler.loader import remove_task_file

        remove_task_file(task, self._schedules_dir)

    async def _fire_once(self, task: ScheduledTask, delay_sec: int) -> None:
        if task.kind == "reminder":
            await self._deliver(task, task.prompt, delay_sec)
            return
        text = await self._execute_task(task)
        await self._deliver(task, text, delay_sec)

    async def _run_and_deliver(self, task: ScheduledTask) -> None:
        text = await self._execute_task(task)
        await self._deliver(task, text, 0)

    async def _deliver(self, task: ScheduledTask, text: str | None, delay_sec: int) -> None:
        """결과를 notify 로 보낸다. text 가 None 이면 실행 실패."""
        if self._notify is None:
            return
        payload = {
            "type": "reminder",
            "id": uuid.uuid4().hex,
            "name": task.name,
            "kind": task.kind,
            "once": task.run_at is not None,
            "title": task.prompt[:160],
            "text": text if text is not None else "실행에 실패했습니다.",
            "error": text is None,
            "delayed_sec": delay_sec,
            "fired_at": datetime.now().astimezone().isoformat(),
        }
        try:
            await self._notify(payload)
        except Exception as exc:
            logger.info(f"[Scheduler] notify failed for '{task.name}': {exc!r}")

    def _on_task_done(self, future: asyncio.Task[None]) -> None:
        """fire-and-forget task의 예외가 소실되지 않도록 로깅."""
        if not future.cancelled() and (exc := future.exception()):
            logger.info(f"[Scheduler] Unhandled exception in background task: {exc!r}")

    async def _execute_task(self, task: ScheduledTask) -> str | None:
        """작업 프롬프트를 새 세션에서 실행하고 최종 답을 돌려준다. 실패하면 None."""
        from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
        from jarvis.core.policy.authenticator import NoAuthAuthenticator
        from jarvis.core.policy.pipeline import SecurityPipeline
        from jarvis.core.policy.policy import AllowAllPolicy
        from jarvis.core.policy.sandbox import PermissiveSandbox
        from jarvis.core.session import AgentSession

        logger.info(f"[Scheduler] Executing task '{task.name}'")

        # Filtered ToolRegistry — only tools_allowed (empty = all tools)
        if task.tools_allowed:
            from jarvis.core.tools.registry import ToolRegistry
            filtered = ToolRegistry()
            for name in task.tools_allowed:
                tool = self._tool_registry.get(name)
                if tool:
                    filtered.register(tool)
        else:
            filtered = self._tool_registry

        # PermissiveSandbox: auto-approve all (no HITL)
        from jarvis.core.policy.validator import DefaultInputValidator
        sandbox = PermissiveSandbox()
        pipeline = SecurityPipeline(
            validator=DefaultInputValidator(),
            authenticator=NoAuthAuthenticator(),
            policy=AllowAllPolicy(),
            sandbox=sandbox,
        )

        session_id = task.session_id or f"sched-{task.name}-{uuid.uuid4().hex[:8]}"
        await self._session_repo.create(session_id=session_id)

        # Reuse memory chain from base_extra but create fresh for isolation
        memory_chain = MemoryMiddlewareChain(stages=[])

        session = AgentSession(
            model=self._model,
            session_id=session_id,
            security_pipeline=pipeline,
            # None 이면 세션이 훅 호출에서 AttributeError 로 실패한다(작업 실패로 보고됨). 앱 조립은 늘 넘긴다
            plugin_runner=self._plugin_runner,  # type: ignore[arg-type]
            memory_chain=memory_chain,
            tool_registry=filtered,
            skill_registry=self._skill_registry,  # type: ignore[arg-type]
            session_repo=self._session_repo,
        )

        try:
            result = await session.prompt(task.prompt)
            logger.info(f"[Scheduler] Task '{task.name}' completed → session {session_id}")
            return result.text() if result is not None else ""
        except Exception as exc:
            logger.info(f"[Scheduler] Task '{task.name}' failed: {exc}")
            return None
