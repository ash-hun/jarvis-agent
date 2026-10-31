"""scheduler 의 ScheduledTask: 기본값, 지정값 보존, 시간대가 붙은 run_at 의 로컬 시각 변환."""

from datetime import datetime, timedelta, timezone

from jarvis.core.scheduler.task import ScheduledTask


def test_task_defaults_to_enabled_new_session_and_all_tools():
    task = ScheduledTask(name="daily", schedule="0 9 * * *", prompt="Good morning")

    assert task.enabled is True
    assert task.session_id is None
    assert task.tools_allowed == []
    assert task.description == ""


def test_task_keeps_given_fields():
    task = ScheduledTask(
        name="weekly-report",
        schedule="0 8 * * 1",
        prompt="Generate weekly report",
        session_id="fixed-session",
        tools_allowed=["bash", "read_file"],
        enabled=False,
        description="Every Monday 08:00",
    )

    assert task.tools_allowed == ["bash", "read_file"]
    assert task.enabled is False
    assert task.session_id == "fixed-session"


def test_aware_run_at_becomes_naive_local_time_comparable_with_now():
    aware = datetime(2026, 10, 27, 16, 44, tzinfo=timezone(timedelta(hours=9)))

    task = ScheduledTask(name="x", prompt="p", run_at=aware.isoformat())

    assert task.run_at is not None and task.run_at.tzinfo is None
    assert task.run_at == aware.astimezone().replace(tzinfo=None)
    assert isinstance(datetime.now() >= task.run_at, bool)
