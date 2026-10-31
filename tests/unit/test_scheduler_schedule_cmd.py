"""scheduler 의 /schedule 핸들러: 한국어 시각 해석, 반복 주기 추론, 작업 등록과 거절 메시지."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from jarvis.core.slash.schedule_cmd import (
    build_schedule_task,
    infer_schedule,
    make_schedule_handler,
    parse_deadline,
    parse_once,
)
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="local")
NOW = datetime(2026, 9, 24, 18, 57, 30)


def _future_day() -> str:
    return (datetime.now() + timedelta(days=5)).strftime("%Y.%m.%d")


@pytest.mark.parametrize(
    ("text", "deadline", "prompt"),
    [
        ("2026.06.01 오전 9시까지 자료 수집해줘", datetime(2026, 6, 1, 9, 0), "자료 수집해줘"),
        ("2026.06.01 오후 3시까지 보고서 작성해줘", datetime(2026, 6, 1, 15, 0), "보고서 작성해줘"),
        ("2026.06.01 오전 12시까지 작업해줘", datetime(2026, 6, 1, 0, 0), "작업해줘"),
        ("2026.06.01 09:30까지 웹 검색해줘", datetime(2026, 6, 1, 9, 30), "웹 검색해줘"),
        (
            "2026.06.01 오전 9시까지 웹검색을 통해 AI 관련 최신 논문을 수집하고 요약해줘",
            datetime(2026, 6, 1, 9, 0),
            "웹검색을 통해 AI 관련 최신 논문을 수집하고 요약해줘",
        ),
    ],
    ids=["am", "pm", "am_12_is_midnight", "24h", "multiword_prompt"],
)
def test_parse_deadline_reads_date_time_and_prompt(text, deadline, prompt):
    assert parse_deadline(text) == (deadline, prompt)


@pytest.mark.parametrize("text", ["내일까지 뭔가 해줘", "", "오늘 저녁에 해줘"])
def test_parse_deadline_returns_none_for_unknown_format(text):
    assert parse_deadline(text) is None


@pytest.mark.parametrize(
    ("left", "cron"),
    [
        (timedelta(days=10), "0 9 * * *"),
        (timedelta(days=3), "0 0,6,12,18 * * *"),
        (timedelta(hours=12), "0 * * * *"),
        (timedelta(minutes=30), "*/10 * * * *"),
    ],
    ids=["daily", "6hourly", "hourly", "10min"],
)
def test_infer_schedule_runs_more_often_as_deadline_nears(left, cron):
    assert infer_schedule(datetime.now() + left) == cron


def test_build_schedule_task_sets_deadline_and_unique_slash_name():
    deadline = datetime(2026, 6, 1, 9, 0)

    task = build_schedule_task(deadline, "웹 검색해줘")
    other = build_schedule_task(deadline, "웹 검색해줘")

    assert task.run_until == deadline
    assert task.prompt == "웹 검색해줘"
    assert task.enabled is True
    assert task.name.startswith("slash-")
    assert task.name != other.name


@pytest.mark.parametrize(
    ("text", "at", "prompt"),
    [
        ("3분 뒤에 물 마시기", (NOW + timedelta(minutes=3)).replace(microsecond=0), "물 마시기"),
        ("1시간 후 스트레칭", NOW + timedelta(hours=1), "스트레칭"),
        ("오후 7시에 알림 하나줘.", datetime(2026, 9, 24, 19, 0), "알림 하나줘."),
        ("오후 6시에 퇴근", datetime(2026, 9, 25, 18, 0), "퇴근"),
        ("내일 오전 9시 30분에 오늘 뉴스 요약해줘", datetime(2026, 9, 25, 9, 30), "오늘 뉴스 요약해줘"),
        ("19:05에 회의", datetime(2026, 9, 24, 19, 5), "회의"),
        ("2026.10.01 오후 7시에 보고서", datetime(2026, 10, 1, 19, 0), "보고서"),
    ],
    ids=[
        "relative_minutes", "relative_hours_without_particle", "ampm_today_when_ahead",
        "passed_time_rolls_to_tomorrow", "tomorrow_with_minutes", "24h_clock", "full_date",
    ],
)
def test_parse_once_reads_run_time_and_prompt(text, at, prompt):
    assert parse_once(text, NOW) == (at, prompt)


def test_parse_once_rejects_until_form():
    assert parse_once("2026.10.01 오후 7시까지 자료 수집", NOW) is None


async def test_handler_registers_recurring_task_until_deadline():
    scheduler = MagicMock()

    out = await make_schedule_handler(scheduler)(f"{_future_day()} 오전 9시까지 웹검색으로 자료 수집해줘", SCOPE)

    assert "등록 완료" in out
    scheduler.add_task.assert_called_once()
    task = scheduler.add_task.call_args[0][0]
    assert task.run_until is not None and task.run_until.hour == 9
    assert "웹검색으로 자료 수집해줘" in task.prompt


async def test_handler_registers_once_task_with_classified_kind_for_calling_agent():
    scheduler = MagicMock()
    classify = AsyncMock(return_value="task")
    scope = MemoryScope(user_id="local", agent_id="karen")

    out = await make_schedule_handler(scheduler, classify)("10분 뒤에 오늘 뉴스 요약해줘", scope)

    task = scheduler.add_task.call_args[0][0]
    assert task.run_at is not None and task.schedule == ""
    assert task.agent == "karen"
    assert task.kind == "task"
    assert task.prompt == "오늘 뉴스 요약해줘"
    classify.assert_awaited_once_with("오늘 뉴스 요약해줘")
    assert "한 번 실행 등록 완료" in out and "작업" in out


@pytest.mark.parametrize(
    "classify",
    [None, AsyncMock(side_effect=RuntimeError("llm down"))],
    ids=["no_classifier", "classifier_fails"],
)
async def test_handler_once_task_defaults_to_reminder(classify):
    scheduler = MagicMock()

    await make_schedule_handler(scheduler, classify)("5분 뒤에 물 마시기", SCOPE)

    assert scheduler.add_task.call_args[0][0].kind == "reminder"


@pytest.mark.parametrize(
    ("args", "has_scheduler", "message"),
    [
        ("", False, "인자가 필요"),
        ("내일 오전에 해줘", False, "파싱 실패"),
        ("{day} 오전 9시까지 자료 수집해줘", False, "비활성화"),
        ("2020.01.01 오전 9시까지 자료 수집해줘", True, "이미 지났"),
        ("2020.01.01 오전 9시에 x", True, "이미 지났"),
        ("{day} 오전 9시까지", True, ""),
    ],
    ids=["no_args", "bad_format", "no_scheduler", "past_deadline", "past_once_time", "empty_prompt"],
)
async def test_handler_rejects_with_message_and_registers_nothing(args, has_scheduler, message):
    scheduler = MagicMock() if has_scheduler else None

    out = await make_schedule_handler(scheduler)(args.format(day=_future_day()), SCOPE)

    assert out and message in out
    if scheduler is not None:
        scheduler.add_task.assert_not_called()
