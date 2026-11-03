"""[core] 스케줄러, 성찰 daemon, 기억 정리, 외부 poller 의 실행을 작업마다 마지막 한 번씩 기록한다."""

import contextlib
from dataclasses import replace
from collections.abc import AsyncIterator, Awaitable, Callable

from jarvis.core.workflow.workflow_types import JobKind, JobRecord

ERROR_CHARS = 200

OnChange = Callable[[JobRecord], Awaitable[None]]


class JobBoard:
    """job_id → JobRecord. 기록만 하고 작업을 고치거나 다시 돌리지 않는다. 알림이 실패해도 작업은 계속된다."""

    def __init__(self, clock: Callable[[], int], on_change: OnChange | None = None) -> None:
        self._clock = clock
        self._on_change = on_change
        self._records: dict[str, JobRecord] = {}

    def set_on_change(self, on_change: OnChange | None) -> None:
        self._on_change = on_change

    def records(self) -> list[JobRecord]:
        """job_id 순. 같은 상태면 같은 목록이다."""
        return [self._records[k] for k in sorted(self._records)]

    async def start(self, job_id: str, kind: JobKind, label: str) -> JobRecord:
        prev = self._records.get(job_id)
        runs = prev.runs + 1 if prev is not None else 1
        base = prev or JobRecord(job_id=job_id, kind=kind, label=label, runs=0, running=False)
        record = replace(base, label=label, runs=runs, running=True, last_started_ms=self._clock())
        self._records[job_id] = record
        await self._notify(record)
        return record

    async def finish(self, job_id: str, ok: bool, error: str = "") -> JobRecord | None:
        """끝을 적는다. 시작하지 않았거나 이미 끝난 작업이면 None 이고 아무것도 바꾸지 않는다."""
        prev = self._records.get(job_id)
        if prev is None or not prev.running:
            return None
        record = replace(prev, running=False, last_ended_ms=self._clock(), last_ok=ok, last_error=error[:ERROR_CHARS])
        self._records[job_id] = record
        await self._notify(record)
        return record

    @contextlib.asynccontextmanager
    async def track(self, job_id: str, kind: JobKind, label: str) -> AsyncIterator[None]:
        """감싼 블록의 시작과 끝을 기록한다. 예외는 기록한 뒤 그대로 올린다."""
        await self.start(job_id, kind, label)
        try:
            yield
        except BaseException as exc:
            await self.finish(job_id, False, repr(exc))
            raise
        await self.finish(job_id, True)

    def wrap(
        self, job_id: str, kind: JobKind, label: str, call: Callable[[], Awaitable[object]]
    ) -> Callable[[], Awaitable[object]]:
        """인자 없는 비동기 콜러블을 track 으로 감싼 콜러블. daemon 대상처럼 넘겨받는 함수에 쓴다."""

        async def tracked() -> object:
            async with self.track(job_id, kind, label):
                return await call()

        return tracked

    async def _notify(self, record: JobRecord) -> None:
        if self._on_change is None:
            return
        with contextlib.suppress(Exception):
            await self._on_change(record)
