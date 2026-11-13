"""[core] 이벤트 루프 지연을 재는 하트비트. 잠든 시간보다 늦게 깨어난 만큼이 지연이다."""

import time
import asyncio
import contextlib
from collections import deque
from dataclasses import dataclass
from collections.abc import Callable

DEFAULT_INTERVAL_SEC = 1.0
# 최근 60초의 최대치를 본다. 좀비(루프가 멈춘 백엔드)는 한 번의 큰 지연보다 이어지는 지연으로 드러난다
DEFAULT_WINDOW = 60


@dataclass(frozen=True)
class LoopLag:
    """마지막 지연과 창 안 최대 지연(ms). samples 는 창 안 표본 수다."""

    last_ms: float
    max_ms: float
    samples: int


def lag_ms(expected_sec: float, slept_sec: float) -> float:
    """잠들려던 시간보다 더 지난 만큼(ms). 일찍 깨는 일은 없으니 음수는 0 으로 둔다. 순수 함수."""
    return max(0.0, (slept_sec - expected_sec) * 1000.0)


class LoopLagMonitor:
    """asyncio 루프에서 주기적으로 잠들고 늦게 깬 만큼을 적는다. start 를 두 번 불러도 작업은 하나다."""

    def __init__(
        self,
        interval_sec: float = DEFAULT_INTERVAL_SEC,
        window: int = DEFAULT_WINDOW,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = interval_sec
        self._monotonic = monotonic
        self._lags: deque[float] = deque(maxlen=window)
        self._task: asyncio.Task[None] | None = None

    def snapshot(self) -> LoopLag:
        if not self._lags:
            return LoopLag(0.0, 0.0, 0)
        return LoopLag(self._lags[-1], max(self._lags), len(self._lags))

    def record(self, expected_sec: float, slept_sec: float) -> float:
        """표본 하나를 적고 그 지연을 돌려준다. 루프 밖(테스트)에서도 쓴다."""
        lag = lag_ms(expected_sec, slept_sec)
        self._lags.append(lag)
        return lag

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        while True:
            started = self._monotonic()
            await asyncio.sleep(self._interval)
            self.record(self._interval, self._monotonic() - started)
