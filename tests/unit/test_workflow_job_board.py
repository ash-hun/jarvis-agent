"""workflow 의 job board: 작업 실행의 시작과 끝, 실패를 작업마다 마지막 한 번씩 적는다."""

import pytest

from jarvis.ui.web.router.workflow_router import merge_jobs
from jarvis.core.workflow.workflow_types import JobRecord
from jarvis.core.workflow.job_board import JobBoard


async def test_track_counts_runs_and_records_failure_then_reraises():
    clock = iter(range(1, 100))
    seen: list[JobRecord] = []

    async def on_change(record: JobRecord) -> None:
        seen.append(record)

    board = JobBoard(clock=lambda: next(clock), on_change=on_change)
    async with board.track("proactive:reflect", "proactive", "성찰"):
        pass
    with pytest.raises(ValueError):
        async with board.track("proactive:reflect", "proactive", "성찰"):
            raise ValueError("boom")

    (record,) = board.records()
    assert (record.runs, record.running, record.last_ok) == (2, False, False)
    assert "boom" in record.last_error and record.last_started_ms == 3 and record.last_ended_ms == 4
    assert [r.running for r in seen] == [True, False, True, False]


async def test_finish_without_start_changes_nothing_and_on_change_failure_is_swallowed():
    async def broken(_record: JobRecord) -> None:
        raise RuntimeError("socket closed")

    board = JobBoard(clock=lambda: 0, on_change=broken)

    assert await board.finish("x", True) is None
    wrapped = board.wrap("memory:consolidate", "consolidate", "정리", _three)
    assert await wrapped() == 3
    assert board.records()[0].last_ok is True


async def _three() -> int:
    return 3


def test_merge_jobs_puts_schedules_first_including_never_run():
    records = [
        JobRecord(job_id="schedule:a", kind="schedule", label="A", runs=2, running=False, last_ok=True),
        JobRecord(job_id="external:poll", kind="external", label="cal", runs=1, running=False),
    ]
    schedules = [
        {"name": "a", "label": "A", "enabled": True, "next_run": "t1", "agent": "main"},
        {"name": "b", "label": "B", "enabled": False, "next_run": None, "agent": "karen"},
    ]

    jobs = merge_jobs(records, schedules)

    assert [(j["job_id"], j["runs"]) for j in jobs] == [("schedule:a", 2), ("schedule:b", 0), ("external:poll", 1)]
    assert jobs[1]["agent"] == "karen" and "next_run" not in jobs[2]
