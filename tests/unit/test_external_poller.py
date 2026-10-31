"""external 기능의 폴러: 소스별 주기, dedup, 실패 격리, 틱 상한, 루프 수명을 검증한다."""

import pytest
import asyncio

from jarvis.core.external import ExternalEvent, ExternalEventInbox, ExternalEventPoller, InMemorySeenStore
from tests.fixtures.external_helpers import Clock, event


class FakeSource:
    def __init__(self, name: str, interval_sec: float, batches: list) -> None:
        self.name = name
        self.interval_sec = interval_sec
        self._batches = list(batches)
        self.calls = 0

    async def poll(self) -> list[ExternalEvent]:
        self.calls += 1
        if not self._batches:
            return []
        item = self._batches.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeTrigger:
    def __init__(self) -> None:
        self.fired = 0

    def fire(self) -> None:
        self.fired += 1


def _poller(sources, *, clock, inbox=None, trigger=None, **kw) -> ExternalEventPoller:
    # 빈 inbox 는 __len__ 때문에 falsy 라 `or` 대신 None 검사로 넘긴다
    inbox = inbox if inbox is not None else ExternalEventInbox()
    return ExternalEventPoller(sources, inbox, InMemorySeenStore(), trigger=trigger, clock=clock, **kw)


async def _record_and_yield(bucket: list[float], delay: float) -> None:
    bucket.append(delay)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_tick_fills_inbox_and_fires_trigger() -> None:
    inbox = ExternalEventInbox()
    trigger = FakeTrigger()
    poller = _poller([FakeSource("cal", 60.0, [[event("cal", "cal:1")]])], clock=Clock(), inbox=inbox, trigger=trigger)

    added = await poller.tick()

    assert added == 1
    assert len(inbox) == 1
    assert trigger.fired == 1


@pytest.mark.asyncio
async def test_tick_respects_per_source_interval() -> None:
    clock = Clock()
    fast = FakeSource("fast", 10.0, [[event("f", f"f:{i}")] for i in range(5)])
    slow = FakeSource("slow", 100.0, [[event("s", f"s:{i}")] for i in range(5)])
    poller = _poller([fast, slow], clock=clock)

    await poller.tick()
    clock.t += 10
    await poller.tick()
    clock.t += 10
    await poller.tick()

    assert fast.calls == 3
    assert slow.calls == 1


@pytest.mark.asyncio
async def test_tick_skips_already_seen_events() -> None:
    same = event("cal", "cal:1")
    clock = Clock()
    poller = _poller([FakeSource("cal", 1.0, [[same], [same]])], clock=clock)

    assert await poller.tick() == 1
    clock.t += 10
    assert await poller.tick() == 0


@pytest.mark.asyncio
async def test_tick_isolates_failing_source() -> None:
    boom = FakeSource("boom", 1.0, [RuntimeError("down")])
    ok = FakeSource("ok", 1.0, [[event("ok", "ok:1")]])
    poller = _poller([boom, ok], clock=Clock())

    assert await poller.tick() == 1


@pytest.mark.asyncio
async def test_tick_caps_events_per_tick() -> None:
    batch = [event("s", f"s:{i}") for i in range(30)]
    poller = _poller([FakeSource("s", 1.0, [batch])], clock=Clock(), max_events_per_tick=5)

    assert await poller.tick() == 5


@pytest.mark.asyncio
async def test_loop_sleeps_until_next_due_and_stops() -> None:
    slept: list[float] = []
    source = FakeSource("cal", 30.0, [[event("cal", "cal:1")]])
    poller = ExternalEventPoller(
        [source],
        ExternalEventInbox(),
        InMemorySeenStore(),
        clock=Clock(),
        sleep=lambda d: _record_and_yield(slept, d),
    )

    await poller.start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await poller.stop()

    assert source.calls >= 1
    assert slept and slept[0] == 30.0
    assert not poller.is_running


@pytest.mark.asyncio
async def test_start_is_noop_without_sources() -> None:
    poller = _poller([], clock=Clock())

    await poller.start()

    assert not poller.is_running
