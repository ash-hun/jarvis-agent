"""[core] 소스별 주기로 외부 세계를 훑어 dedup 하고 inbox 에 적재한 뒤 성찰 트리거를 깨운다."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable

from jarvis.common.logger import get_logger
from jarvis.core.external.dedup import SeenStore
from jarvis.core.external.inbox import ExternalEventInbox
from jarvis.core.external.protocol import ExternalSource
from jarvis.core.external.types import ExternalEvent
from jarvis.core.proactive.triggers import ExternalTrigger

Sleeper = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]

logger = get_logger(__name__)


class ExternalEventPoller:
    """소스별 주기로 외부 세계를 훑어 dedup → inbox 적재 → 트리거 발화.

    SchedulerService·ProactivityDaemon의 형제. 순수하게 주기·생명주기만 맡고,
    "무엇을 감지할지"는 주입된 소스가, "말할지"는 기존 proactive policy가 정한다.
    sleep/clock을 주입할 수 있어 실시간 대기 없이 루프를 검증한다.
    """

    def __init__(
        self,
        sources: list[ExternalSource],
        inbox: ExternalEventInbox,
        seen: SeenStore,
        *,
        trigger: ExternalTrigger | None = None,
        max_events_per_tick: int = 20,
        sleep: Sleeper = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        self._sources = sources
        self._inbox = inbox
        self._seen = seen
        self._trigger = trigger
        self._max_events = max_events_per_tick
        self._sleep = sleep
        self._clock = clock
        # 최초 틱에서 전 소스를 즉시 1회 폴링한다(기동 직후 현재 상태 파악).
        self._next_due: dict[str, float] = {s.name: 0.0 for s in sources}
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running or not self._sources:
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

    async def tick(self) -> int:
        """주기가 도래한 소스를 1회씩 폴링하고 새 이벤트 건수를 반환."""
        now = self._clock()
        collected: list[ExternalEvent] = []
        for source in self._sources:
            if self._next_due.get(source.name, 0.0) > now:
                continue
            self._next_due[source.name] = now + source.interval_sec
            # 소스별 예외 격리 — 한 소스의 실패가 루프를 죽이지 않는다.
            try:
                collected.extend(await source.poll())
            except Exception as exc:
                logger.info(f"[ExternalEventPoller] '{source.name}' poll failed: {exc}")

        if not collected:
            return 0

        try:
            fresh = await self._seen.filter_new(collected)
        except Exception as exc:
            logger.info(f"[ExternalEventPoller] dedup failed: {exc}")
            return 0

        if not fresh:
            return 0

        if len(fresh) > self._max_events:
            logger.info(
                f"[ExternalEventPoller] {len(fresh)}건 중 상한 {self._max_events}건만 "
                f"이번 틱에 전달"
            )
            fresh = fresh[: self._max_events]

        self._inbox.put(fresh)
        if self._trigger is not None:
            self._trigger.fire()
        return len(fresh)

    def _sleep_seconds(self) -> float:
        """다음 도래 시각까지의 대기 시간(최소 1초)."""
        if not self._sources:
            return 1.0
        now = self._clock()
        remaining = [max(0.0, self._next_due.get(s.name, 0.0) - now) for s in self._sources]
        return max(1.0, min(remaining))

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except Exception as exc:
                logger.info(f"[ExternalEventPoller] tick failed: {exc}")
            if not self._running:
                break
            await self._sleep(self._sleep_seconds())

    @property
    def is_running(self) -> bool:
        return self._running
