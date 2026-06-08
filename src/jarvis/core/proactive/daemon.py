from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable

# 성찰 1회 — 보통 AgentSession.reflect 바인딩.
ReflectOnce = Callable[[], Awaitable[object]]
# 매 틱마다 "지금 성찰할 대상들"을 돌려주는 provider. 세션 전환/추가를 자동 추종.
ReflectTargets = Callable[[], Iterable[ReflectOnce]]
Sleeper = Callable[[float], Awaitable[None]]


class ProactivityDaemon:
    """요청 없이 도는 백그라운드 성찰 루프 (B3) — SchedulerService의 형제.

    "무엇을 성찰할지"는 주입된 targets provider(보통 활성 세션들의 reflect)가
    소유하고, 데몬은 순수하게 주기·생명주기만 관리한다 → session/UI와 분리,
    단위 테스트 용이. provider를 매 틱 재평가하므로 멀티세션·세션 전환을 추종한다.
    sleep을 주입할 수 있어 실시간 대기 없이 루프를 검증한다.
    """

    def __init__(
        self,
        targets: ReflectTargets,
        *,
        interval_sec: float,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._targets = targets
        self._interval = interval_sec
        self._sleep = sleep
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def tick(self) -> None:
        """현재 대상 전체를 1회씩 성찰. 대상별 실패가 루프를 죽이지 않도록 격리."""
        try:
            targets = list(self._targets())
        except Exception:
            return
        for reflect in targets:
            with contextlib.suppress(Exception):
                await reflect()

    async def _loop(self) -> None:
        # 가동 직후 즉시 말 걸지 않도록 sleep 먼저(휴지기 후 성찰).
        while self._running:
            await self._sleep(self._interval)
            if not self._running:
                break
            await self.tick()

    @property
    def is_running(self) -> bool:
        return self._running
