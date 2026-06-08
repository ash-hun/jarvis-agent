from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

Sleeper = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class ActivityClock:
    """사용자 활동 시각을 공유하는 경량 객체. 세션이 touch(), 트리거가 idle_seconds()."""

    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._last = clock()

    def touch(self) -> None:
        self._last = self._clock()

    def idle_seconds(self) -> float:
        return self._clock() - self._last


@runtime_checkable
class ReflectionTrigger(Protocol):
    """daemon이 "언제 성찰할지" 결정하는 교체 가능한 트리거.

    wait()는 다음 성찰 시점까지 블록한다. notify_activity()는 사용자 활동을
    트리거에 알린다(idle 류만 의미 있음, 그 외엔 no-op).
    """

    async def wait(self) -> None: ...

    def notify_activity(self) -> None: ...


class IntervalTrigger:
    """고정 주기 트리거 — 기존 동작(시간 기반)."""

    def __init__(self, interval_sec: float, sleep: Sleeper = asyncio.sleep) -> None:
        self._interval = interval_sec
        self._sleep = sleep

    async def wait(self) -> None:
        await self._sleep(self._interval)

    def notify_activity(self) -> None:
        pass


class IdleTrigger:
    """사용자가 idle_sec 동안 조용할 때 1회 발화 — 대화 중엔 끼어들지 않는다.

    활동(touch)이 들어오면 카운트가 리셋되고 다시 발화 가능해진다.
    """

    def __init__(
        self,
        activity: ActivityClock,
        idle_sec: float,
        *,
        poll_sec: float | None = None,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._activity = activity
        self._idle = idle_sec
        self._poll = poll_sec if poll_sec is not None else min(idle_sec, 30.0) or 1.0
        self._sleep = sleep
        self._fired = False
        self._last_seen = activity.idle_seconds()

    def notify_activity(self) -> None:
        self._fired = False  # 활동 발생 → 다음 idle에 다시 발화 허용

    async def wait(self) -> None:
        while True:
            idle = self._activity.idle_seconds()
            # 활동으로 idle이 줄면(리셋) 재발화 허용.
            if idle < self._last_seen:
                self._fired = False
            self._last_seen = idle

            if idle >= self._idle and not self._fired:
                self._fired = True
                return
            remaining = self._idle - idle
            await self._sleep(min(self._poll, remaining) if remaining > 0 else self._poll)


class ExternalTrigger:
    """외부 이벤트로 발화하는 트리거. fire()로 즉시 깨운다.

    MCP 캘린더·메일 폴러 등 외부 감지기가 이 fire()에 꽂힌다(플러그 지점).
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def fire(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()
        self._event.clear()

    def notify_activity(self) -> None:
        pass


class AnyTrigger:
    """여러 트리거 중 하나라도 발화하면 깨어나는 합성 트리거(race)."""

    def __init__(self, triggers: list[ReflectionTrigger]) -> None:
        self._triggers = triggers

    async def wait(self) -> None:
        tasks = [asyncio.ensure_future(t.wait()) for t in self._triggers]
        try:
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for p in pending:
                p.cancel()
            for p in pending:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await p

    def notify_activity(self) -> None:
        for t in self._triggers:
            t.notify_activity()
