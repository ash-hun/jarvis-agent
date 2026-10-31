"""scheduler 기능: AGENDA 의 작업 켜고 끄기, 한 번 알림 표시, 화면이 없을 때 울린 알림의 다음 접속 전달을 검증한다."""

import pytest
import asyncio
from datetime import datetime, timedelta

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import agenda_assembly, web_client  # noqa: E402
from jarvis.core.scheduler.task import ScheduledTask  # noqa: E402


@pytest.fixture
def agenda(monkeypatch, tmp_path):
    assembly, scheduler = agenda_assembly(monkeypatch, tmp_path)
    with web_client(assembly) as c:
        yield c, scheduler


def test_schedule_toggle_turns_task_off(agenda):
    client, scheduler = agenda

    resp = client.post("/api/schedules/late", json={"enabled": False})

    assert resp.status_code == 200
    assert scheduler.get_task("late").enabled is False


@pytest.mark.parametrize(("name", "enabled", "code"), [("late", "no", 400), ("ghost", True, 404)])
def test_schedule_toggle_rejects_bad_value_and_unknown_task(agenda, name, enabled, code):
    client, _ = agenda

    resp = client.post(f"/api/schedules/{name}", json={"enabled": enabled})

    assert resp.status_code == code


def test_agenda_marks_once_reminders(agenda):
    client, scheduler = agenda
    run_at = datetime.now().replace(microsecond=0) + timedelta(minutes=3)
    scheduler.add_task(ScheduledTask(name="once-x", prompt="물 마시기", kind="reminder", run_at=run_at))

    item = next(s for s in client.get("/api/agenda").json()["schedules"] if s["name"] == "once-x")

    assert item["once"] is True and item["kind"] == "reminder"
    assert item["next_run"].startswith(run_at.isoformat())


def test_notice_without_open_hud_is_delivered_on_next_connect(agenda):
    client, scheduler = agenda

    async def fire() -> None:
        scheduler.run_soon(ScheduledTask(name="water", prompt="물 마시기", kind="reminder"))
        await asyncio.gather(*(t for t in asyncio.all_tasks() if t is not asyncio.current_task()))

    asyncio.run(fire())
    with client.websocket_connect("/ws?session_id=default") as ws:
        hello = ws.receive_json()
        notice = ws.receive_json()

    assert hello["type"] == "connected"
    assert notice["type"] == "reminder" and notice["text"] == "물 마시기"
    assert notice["missed"] is True
