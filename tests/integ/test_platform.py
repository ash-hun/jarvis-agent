"""platform 기능: /api/platform/metrics 가 프로세스 자원, 루프 지연, 스케줄 작업의 에이전트별 상태를 낸다."""

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import agenda_assembly, web_client  # noqa: E402
from jarvis.core.scheduler.task import ScheduledTask  # noqa: E402


def test_metrics_fold_schedule_runs_into_their_agent(monkeypatch, tmp_path):
    assembly, scheduler = agenda_assembly(monkeypatch, tmp_path)
    ping = ScheduledTask(name="ping", schedule="0 22 * * *", prompt="물 마시기", kind="reminder", agent="main")
    scheduler.ensure_task(ping)

    with web_client(assembly) as client:
        client.portal.call(scheduler._run_and_deliver, ping)
        body = client.get("/api/platform/metrics").json()

    agents = {a["agent"]: a for a in body["agents"]}
    assert agents["main"]["jobs"] == 1 and agents["main"]["fail_streak"] == 0 and agents["main"]["last_ok_ms"]
    assert agents["main"]["scheduled"] is True and agents["shared"]["scheduled"] is False
    assert "shared" in agents and body["process"]["rss_bytes"] > 0 and body["loop_lag"]["samples"] >= 0
