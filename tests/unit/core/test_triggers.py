"""Proactive 성찰 트리거(Tier 2 C2) — interval / idle / external / composite."""
from __future__ import annotations

import asyncio

import pytest

from jarvis.core.proactive import (
    ActivityClock,
    AnyTrigger,
    ExternalTrigger,
    IdleTrigger,
    IntervalTrigger,
    ProactivityDaemon,
    ReflectionTrigger,
)


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_triggers_satisfy_protocol():
    clock = ActivityClock()
    assert isinstance(IntervalTrigger(1.0), ReflectionTrigger)
    assert isinstance(IdleTrigger(clock, 1.0), ReflectionTrigger)
    assert isinstance(ExternalTrigger(), ReflectionTrigger)
    assert isinstance(AnyTrigger([IntervalTrigger(1.0)]), ReflectionTrigger)


@pytest.mark.asyncio
async def test_interval_trigger_uses_sleep():
    slept: list = []

    async def fake_sleep(d):
        slept.append(d)

    trig = IntervalTrigger(5.0, sleep=fake_sleep)
    await trig.wait()
    assert slept == [5.0]


def test_activity_clock_touch_resets_idle():
    c = _Clock()
    ac = ActivityClock(clock=c)
    c.t += 50
    assert ac.idle_seconds() == 50
    ac.touch()
    assert ac.idle_seconds() == 0


@pytest.mark.asyncio
async def test_idle_trigger_fires_only_after_idle_period():
    c = _Clock()
    ac = ActivityClock(clock=c)

    async def fake_sleep(_):
        # 한 번 sleep할 때마다 시간 전진.
        c.t += 60

    trig = IdleTrigger(ac, idle_sec=120, poll_sec=60, sleep=fake_sleep)
    # 0s idle → 미발화, sleep → 60s, 아직 < 120 → sleep → 120s → 발화.
    await trig.wait()
    assert ac.idle_seconds() >= 120


@pytest.mark.asyncio
async def test_idle_trigger_refires_only_after_activity():
    c = _Clock()
    ac = ActivityClock(clock=c)

    async def fake_sleep(_):
        c.t += 200  # 곧장 idle 초과

    trig = IdleTrigger(ac, idle_sec=120, poll_sec=60, sleep=fake_sleep)
    await trig.wait()  # 1회 발화
    # 활동 없이 다시 wait하면, 이미 fired라 같은 idle 구간에선 재발화 보류.
    # 활동을 주면 재발화 허용.
    ac.touch()
    trig.notify_activity()
    await trig.wait()  # 활동 후 다시 idle → 발화
    assert ac.idle_seconds() >= 120


@pytest.mark.asyncio
async def test_external_trigger_fires_on_demand():
    trig = ExternalTrigger()
    waiter = asyncio.ensure_future(trig.wait())
    await asyncio.sleep(0)
    assert not waiter.done()
    trig.fire()
    await asyncio.wait_for(waiter, timeout=1.0)


@pytest.mark.asyncio
async def test_any_trigger_wakes_on_first():
    fired = ExternalTrigger()

    class _Never:
        async def wait(self):
            await asyncio.sleep(3600)

        def notify_activity(self):
            pass

    trig = AnyTrigger([_Never(), fired])
    waiter = asyncio.ensure_future(trig.wait())
    await asyncio.sleep(0)
    fired.fire()
    await asyncio.wait_for(waiter, timeout=1.0)  # 한쪽만 발화해도 깨어남


@pytest.mark.asyncio
async def test_daemon_uses_external_trigger():
    calls = {"n": 0}
    trig = ExternalTrigger()

    async def reflect():
        calls["n"] += 1

    daemon = ProactivityDaemon(lambda: [reflect], trigger=trig)
    await daemon.start()
    trig.fire()
    for _ in range(50):
        if calls["n"] >= 1:
            break
        await asyncio.sleep(0.005)
    await daemon.stop()
    assert calls["n"] >= 1
