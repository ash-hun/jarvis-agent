from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

from jarvis.core.scheduler.task import ScheduledTask

if TYPE_CHECKING:
    from jarvis.agent_layer.session.protocol import SessionRepo
    from jarvis.core.tools.registry import ToolRegistry
    from jarvis.model_layer.types import ModelConfig


class SchedulerService:
    """
    croniter 기반 스케줄 루프.
    - 각 작업은 PermissiveSandbox + 필터된 ToolRegistry로 실행
    - HITL approval 없이 자율 실행
    """

    def __init__(
        self,
        tasks: list[ScheduledTask],
        session_repo: SessionRepo,
        tool_registry: ToolRegistry,
        model: ModelConfig,
        base_extra: dict[str, Any],
    ) -> None:
        self._tasks = tasks
        self._session_repo = session_repo
        self._tool_registry = tool_registry
        self._model = model
        self._base_extra = base_extra
        self._running = False
        self._task_handle: asyncio.Task[None] | None = None

    @property
    def task_count(self) -> int:
        return len([t for t in self._tasks if t.enabled])

    def add_task(self, task: ScheduledTask) -> None:
        self._tasks.append(task)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task_handle = asyncio.create_task(self._loop())
        print(f"[Scheduler] Started with {self.task_count} enabled task(s)")

    async def stop(self) -> None:
        import contextlib
        self._running = False
        if self._task_handle:
            self._task_handle.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task_handle
        print("[Scheduler] Stopped")

    async def _loop(self) -> None:
        try:
            from croniter import croniter
        except ImportError:
            print("[Scheduler] croniter not installed — scheduler disabled. Run: uv sync --extra scheduler")
            return

        import time
        from datetime import datetime
        # last_run[task_name] = epoch when it last ran (0 = never)
        last_run: dict[str, float] = {}

        while self._running:
            now = time.time()
            now_dt = datetime.now()
            for task in self._tasks:
                if not task.enabled:
                    continue
                # 마감 시각이 지난 슬래시 명령 작업은 자동 만료
                if task.run_until is not None and now_dt >= task.run_until:
                    task.enabled = False
                    print(f"[Scheduler] Task '{task.name}' expired (run_until={task.run_until})")
                    continue
                try:
                    cron = croniter(task.schedule, now)
                    prev = cron.get_prev(float)
                    # Fire if previous cron tick is within the last 60s and not yet run
                    if now - prev < 60 and last_run.get(task.name, 0) < prev:
                        last_run[task.name] = now
                        t = asyncio.create_task(self._execute_task(task))
                        t.add_done_callback(self._on_task_done)
                except Exception as exc:
                    print(f"[Scheduler] Cron parse error for '{task.name}': {exc}")

            await asyncio.sleep(30)

    def _on_task_done(self, future: asyncio.Task[None]) -> None:
        """fire-and-forget task의 예외가 소실되지 않도록 로깅."""
        if not future.cancelled() and (exc := future.exception()):
            print(f"[Scheduler] Unhandled exception in background task: {exc!r}")

    async def _execute_task(self, task: ScheduledTask) -> None:
        from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
        from jarvis.core.policy.authenticator import NoAuthAuthenticator
        from jarvis.core.policy.pipeline import SecurityPipeline
        from jarvis.core.policy.policy import AllowAllPolicy
        from jarvis.core.policy.sandbox import PermissiveSandbox
        from jarvis.core.session import AgentSession

        print(f"[Scheduler] Executing task '{task.name}'")

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

        extra = {**self._base_extra, "pipeline": pipeline, "sandbox": sandbox}

        # Reuse memory chain from base_extra but create fresh for isolation
        memory_chain = MemoryMiddlewareChain(stages=[])

        session = AgentSession(
            model=self._model,
            session_id=session_id,
            security_pipeline=pipeline,
            plugin_runner=extra.get("plugin_runner"),
            memory_chain=memory_chain,
            tool_registry=filtered,
            skill_registry=extra.get("skill_registry"),
            session_repo=self._session_repo,
        )

        try:
            await session.prompt(task.prompt)
            print(f"[Scheduler] Task '{task.name}' completed → session {session_id}")
        except Exception as exc:
            print(f"[Scheduler] Task '{task.name}' failed: {exc}")
