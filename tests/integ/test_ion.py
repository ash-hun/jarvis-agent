"""ion 기능: /ion 이 상태, 사고, 로그를 내고 답과 재기동을 받아 행동하며, Ion 도구가 그 HTTP 를 거친다."""

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from jarvis.core.tools.ion.ion_tools import IonIncidentsTool, IonReportTool, IonRespondTool  # noqa: E402
from tests.unit.test_ion_watch_service import FakeBackend, FakeDocker, _service  # noqa: E402
from jarvis.core.tools.ion.ion_client import IonClient  # noqa: E402
from jarvis.ion.ion_app import EventHub, build_ion_app  # noqa: E402
from jarvis.ion.incident_store import Incident  # noqa: E402
from jarvis.ion.watch_service import sse_line  # noqa: E402


def _app(tmp_path, key: str | None):  # type: ignore[no-untyped-def]
    backend, docker = FakeBackend(), FakeDocker()
    backend.ok = False
    # 배경 루프는 한 시간에 한 번만 돌게 해 두고 tick 은 테스트가 직접 부른다
    svc, _ = _service(tmp_path, backend, docker, poll_sec=3600)
    return build_ion_app(svc, EventHub(), key), svc, docker


def test_backend_outage_shows_as_incident_and_restart_response_acts_once(tmp_path):
    app, svc, docker = _app(tmp_path, None)
    with TestClient(app) as client:
        for _ in range(3):
            client.portal.call(svc.tick)
        status = client.get("/ion/status").json()
        (incident,) = status["incidents"]
        assert status["backend_ok"] is False and incident["kind"] == "backend_down"

        first = client.post(f"/ion/incidents/{incident['id']}/respond", json={"action": "restart"})
        again = client.post(f"/ion/incidents/{incident['id']}/respond", json={"action": "restart"})
        assert first.status_code == 200 and first.json()["incident"]["action_result"] == "재기동함"
        assert again.json() == first.json() and docker.restarts == 1
        assert client.post("/ion/incidents/ghost/respond", json={"action": "restart"}).status_code == 404
        assert client.post(f"/ion/incidents/{incident['id']}/respond", json={"action": "nap"}).status_code == 400


def test_access_key_guards_every_route(tmp_path):
    app, _, _ = _app(tmp_path, "secret")
    with TestClient(app) as client:
        assert client.get("/ion/status").status_code == 401
        assert client.get("/ion/status", headers={"Authorization": "Bearer secret"}).status_code == 200
        assert client.get("/ion/status", params={"token": "secret"}).status_code == 200


async def test_event_hub_streams_hello_then_published_events():
    hub = EventHub()
    stream = hub.stream()
    assert await anext(stream) == sse_line({"type": "hello"})
    await hub.publish({"type": "incident", "id": "x"})
    assert await anext(stream) == sse_line({"type": "incident", "id": "x"})
    await stream.aclose()


def _tool_client(app, key: str) -> IonClient:  # type: ignore[no-untyped-def]
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ion",
                             headers={"Authorization": f"Bearer {key}"})
    return IonClient("http://ion", key, client=http)


async def test_ion_tools_reach_incidents_logs_and_actions_through_the_ion_http(tmp_path):
    app, svc, docker = _app(tmp_path, "key")
    svc.store.open(Incident("backend_down:backend:1000", "backend_down", "backend", "health 실패 3회 연속", 1000))
    svc.store.open(Incident("agent_failing:karen:700000", "agent_failing", "karen", "연속 실패 3회", 700_000))
    svc.store.respond("backend_down:backend:1000", "restart", 2000, "재기동함")
    svc.store.close("backend_down:backend:1000", 3000)
    client = _tool_client(app, "key")

    listed = (await IonIncidentsTool(client).execute("c1", {})).content[0].text
    assert listed.index("agent_failing:karen:700000") < listed.index("backend_down:backend:1000")
    assert "닫힘" in listed and "열려 있음" in listed

    report = (await IonReportTool(client).execute("c2", {"incident_id": "agent_failing:karen:700000"})).content[0].text
    # 연 시각 10분 전부터, 아직 열려 있어 끝은 없이, 기본 200줄
    assert "[Loop] boom" in report and docker.log_calls == [(100, None, 200)]

    params = {"action": "pause", "incident_id": "agent_failing:karen:700000"}
    answered = await IonRespondTool(client).execute("c3", params)
    assert answered.is_error is False and "작업 1개 멈춤" in answered.content[0].text
    restarted = await IonRespondTool(client).execute("c4", {"action": "restart"})
    assert restarted.is_error is False and docker.restarts == 1

    assert (await IonIncidentsTool(_tool_client(app, "wrong")).execute("c5", {})).is_error is True


async def test_incident_titles_use_the_agent_display_name_from_metrics(tmp_path):
    backend, docker = FakeBackend(), FakeDocker()
    backend.rows = [{"agent": "karen", "name": "K.A.R.E.N.", "fail_streak": 3, "jobs": 1}]
    svc, _ = _service(tmp_path, backend, docker, poll_sec=3600)
    app = build_ion_app(svc, EventHub(), None)
    await svc.tick()
    with TestClient(app) as client:
        rows = client.get("/ion/incidents").json()["incidents"]
    assert [(r["target"], r["title"]) for r in rows] == [("karen", "Ion: K.A.R.E.N. 의 작업이 계속 실패해요")]
