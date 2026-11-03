"""workflow 기능: 위임 도구 호출이 관계 간선으로 ws 와 /api/workflow 에 보이고, 스케줄 실행이 /api/jobs 에 남는다."""

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import (  # noqa: E402
    run_turn,
    web_client,
    scripted_env,
    use_provider,
    web_assembly,
    agenda_assembly,
)
from tests.fixtures.team_provider import TeamProvider  # noqa: E402

KAREN = (
    "name: K.A.R.E.N.\ndescription: 정보 수집\nsystem_prompt: 당신은 카렌입니다.\n"
    "tools: [read_file]\nproactive: false\n"
)


@pytest.fixture
def provider():
    yield from use_provider(TeamProvider())


@pytest.fixture
def team_assembly(monkeypatch, tmp_path, provider):
    (tmp_path / "team").mkdir()
    (tmp_path / "team" / "karen.yaml").write_text(KAREN)
    return web_assembly(monkeypatch, tmp_path, **scripted_env("team", tmp_path, tmp_path / "team"))


def test_ask_agent_turn_becomes_delegation_edges(team_assembly):
    with web_client(team_assembly) as client:
        with client.websocket_connect("/ws?session_id=default") as ws:
            ws.receive_json()
            seen = run_turn(ws, "카렌에게 AI 뉴스 좀 물어봐")
        graph = client.get("/api/workflow").json()

    pushed = [m["edge"] for m in seen if m["type"] == "workflow_changed"]
    routes = {(e["source"], e["target"], e["kind"]) for e in pushed}
    assert routes >= {("main", "karen", "ask"), ("karen", "main", "ask")}
    assert [a["id"] for a in graph["agents"]] == ["main", "karen"]
    done = [(e["source"], e["target"], e["ok"]) for e in graph["edges"]]
    assert ("main", "karen", True) in done and ("karen", "main", True) in done
    assert all(e["ended_ms"] >= e["started_ms"] for e in graph["edges"])
    caps = graph["capabilities"]
    assert {"name", "description", "approval", "agents"} <= set(caps[0])
    assert all(set(c["agents"]) <= {"main", "karen"} for c in caps)
    shared = next(c for c in caps if c["name"] == "ask_agent")
    assert shared["agents"] == ["main", "karen"]
    assert [len(c["agents"]) > 1 for c in caps] == sorted(len(c["agents"]) > 1 for c in caps)


def test_jobs_list_schedules_before_and_after_a_run(monkeypatch, tmp_path):
    from jarvis.core.scheduler.task import ScheduledTask

    assembly, scheduler = agenda_assembly(monkeypatch, tmp_path)
    ping = ScheduledTask(name="ping", schedule="0 22 * * *", prompt="물 마시기", kind="reminder")
    scheduler.ensure_task(ping)

    with web_client(assembly) as client:
        before = client.get("/api/jobs").json()
        client.portal.call(scheduler._run_and_deliver, ping)
        after = client.get("/api/jobs").json()

    first = {j["job_id"]: j for j in before["jobs"]}
    assert first["schedule:ping"]["runs"] == 0 and first["schedule:ping"]["next_run"]
    assert first["schedule:off"]["enabled"] is False and first["schedule:off"]["next_run"] is None
    ran = {j["job_id"]: j for j in after["jobs"]}["schedule:ping"]
    assert (ran["runs"], ran["running"], ran["last_ok"]) == (1, False, True)
    assert before["daemon"]["enabled"] is False
