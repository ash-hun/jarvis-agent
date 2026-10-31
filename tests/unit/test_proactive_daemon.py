"""proactive: ProactivityDaemon 이 틱마다 대상을 다시 골라 성찰시키고 생명주기를 한 벌만 돌리는지 검증한다."""

import pytest
import asyncio

from jarvis.core.proactive import ExternalTrigger, ProactivityDaemon


@pytest.mark.asyncio
async def test_tick_reflects_every_target():
    calls = {"a": 0, "b": 0}

    async def ra():
        calls["a"] += 1

    async def rb():
        calls["b"] += 1

    await ProactivityDaemon(lambda: [ra, rb], interval_sec=0).tick()

    assert calls == {"a": 1, "b": 1}


@pytest.mark.asyncio
async def test_tick_reevaluates_targets_each_time():
    calls = {"n": 0}
    state: dict[str, list] = {"targets": []}

    async def reflect():
        calls["n"] += 1

    daemon = ProactivityDaemon(lambda: state["targets"], interval_sec=0)
    await daemon.tick()
    before = calls["n"]
    state["targets"] = [reflect]

    await daemon.tick()

    assert (before, calls["n"]) == (0, 1)


@pytest.mark.asyncio
async def test_tick_isolates_target_failure():
    calls = {"ok": 0}

    async def boom():
        raise RuntimeError("reflect down")

    async def ok():
        calls["ok"] += 1

    await ProactivityDaemon(lambda: [boom, ok], interval_sec=0).tick()

    assert calls["ok"] == 1


@pytest.mark.asyncio
async def test_loop_runs_ticks_until_stopped():
    calls = {"n": 0}
    stop_evt = asyncio.Event()

    async def reflect():
        calls["n"] += 1

    async def fake_sleep(_):
        if calls["n"] >= 2:
            stop_evt.set()
            await asyncio.sleep(3600)

    daemon = ProactivityDaemon(lambda: [reflect], interval_sec=0, sleep=fake_sleep)
    await daemon.start()
    running = daemon.is_running
    await asyncio.wait_for(stop_evt.wait(), timeout=1.0)

    await daemon.stop()

    assert running is True
    assert calls["n"] == 2
    assert daemon.is_running is False


@pytest.mark.asyncio
async def test_start_twice_runs_one_loop():
    waits: list[float] = []

    async def reflect():
        return None

    async def never(d):
        waits.append(d)
        await asyncio.sleep(3600)

    daemon = ProactivityDaemon(lambda: [reflect], interval_sec=0, sleep=never)
    await daemon.start()

    await daemon.start()

    await asyncio.sleep(0.01)
    await daemon.stop()
    assert len(waits) == 1


@pytest.mark.asyncio
async def test_loop_wakes_on_external_trigger():
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
