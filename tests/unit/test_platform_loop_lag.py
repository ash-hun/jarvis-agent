"""platform 의 루프 지연: 늦게 깬 만큼만 지연으로 적고, 감시 작업은 두 번 켜도 하나다."""

import asyncio

from jarvis.core.platform.loop_lag import LoopLagMonitor, lag_ms


def test_lag_is_the_oversleep_in_ms_and_never_negative():
    assert lag_ms(1.0, 1.25) == 250.0
    assert lag_ms(1.0, 0.9) == 0.0


def test_snapshot_keeps_last_and_window_max():
    monitor = LoopLagMonitor(window=2)
    monitor.record(1.0, 2.0)
    monitor.record(1.0, 1.5)
    monitor.record(1.0, 1.25)

    snap = monitor.snapshot()
    assert (snap.last_ms, snap.max_ms, snap.samples) == (250.0, 500.0, 2)


async def test_start_twice_runs_one_task_and_stop_ends_it():
    monitor = LoopLagMonitor(interval_sec=0.01)
    await monitor.start()
    first = monitor._task
    await monitor.start()
    assert monitor._task is first
    await asyncio.sleep(0.05)
    await monitor.stop()
    assert monitor._task is None and monitor.snapshot().samples >= 1
