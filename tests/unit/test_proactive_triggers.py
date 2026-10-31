"""proactive: 성찰 트리거(주기, 유휴, 외부, 합성)가 언제 깨어나고 취소될 때 무엇을 남기는지 검증한다."""

import pytest
import asyncio

from jarvis.core.proactive import (
    ActivityClock,
    AnyTrigger,
    ExternalTrigger,
    IdleTrigger,
    IntervalTrigger,
    ReflectionTrigger,
)


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _NeverFires(ReflectionTrigger):
    def __init__(self) -> None:
        self.cancelled = False

    async def wait(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def test_triggers_satisfy_protocol():
    clock = ActivityClock()

    triggers = [IntervalTrigger(1.0), IdleTrigger(clock, 1.0), ExternalTrigger(), AnyTrigger([IntervalTrigger(1.0)])]

    assert all(isinstance(t, ReflectionTrigger) for t in triggers)


@pytest.mark.asyncio
async def test_interval_trigger_waits_with_injected_sleep():
    slept: list[float] = []

    async def fake_sleep(d):
        slept.append(d)

    await IntervalTrigger(5.0, sleep=fake_sleep).wait()

    assert slept == [5.0]


def test_activity_clock_touch_resets_idle():
    c = _Clock()
    ac = ActivityClock(clock=c)
    c.t += 50
    before = ac.idle_seconds()

    ac.touch()

    assert (before, ac.idle_seconds()) == (50, 0)


@pytest.mark.asyncio
async def test_idle_trigger_fires_only_after_idle_period():
    c = _Clock()
    ac = ActivityClock(clock=c)

    async def fake_sleep(_):
        c.t += 60

    await IdleTrigger(ac, idle_sec=120, poll_sec=60, sleep=fake_sleep).wait()

    assert ac.idle_seconds() >= 120


@pytest.mark.asyncio
async def test_idle_trigger_refires_after_activity():
    c = _Clock()
    ac = ActivityClock(clock=c)

    async def fake_sleep(_):
        c.t += 200

    trig = IdleTrigger(ac, idle_sec=120, poll_sec=60, sleep=fake_sleep)
    await trig.wait()
    ac.touch()
    trig.notify_activity()

    await trig.wait()

    assert ac.idle_seconds() >= 120


@pytest.mark.asyncio
async def test_external_trigger_fires_on_demand():
    trig = ExternalTrigger()
    waiter = asyncio.ensure_future(trig.wait())
    await asyncio.sleep(0)
    pending = not waiter.done()

    trig.fire()

    await asyncio.wait_for(waiter, timeout=1.0)
    assert pending


@pytest.mark.asyncio
async def test_any_trigger_wakes_on_first_child():
    fired = ExternalTrigger()
    waiter = asyncio.ensure_future(AnyTrigger([_NeverFires(), fired]).wait())
    await asyncio.sleep(0)

    fired.fire()

    await asyncio.wait_for(waiter, timeout=1.0)


@pytest.mark.asyncio
async def test_any_trigger_cancel_cancels_children():
    children = [_NeverFires(), _NeverFires()]
    waiter = asyncio.ensure_future(AnyTrigger(list(children)).wait())
    await asyncio.sleep(0.01)

    waiter.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert all(c.cancelled for c in children)


async def test_reflection_trigger_default_never_fires_nor_blocks_any_trigger():
    trigger = ReflectionTrigger()
    trigger.notify_activity()
    external = ExternalTrigger()
    external.fire()

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(trigger.wait(), timeout=0.01)
    await asyncio.wait_for(AnyTrigger([ReflectionTrigger(), external]).wait(), timeout=1.0)
