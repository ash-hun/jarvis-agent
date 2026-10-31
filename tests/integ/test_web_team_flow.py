"""Web HUD 최상위 에이전트 시나리오: 에이전트 목록, 에이전트별 세션 만들기, ws 연결, 분기, 재시작 뒤 다시 열기."""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from jarvis.jarvis_config import JarvisSettings  # noqa: E402
from jarvis.app.infra_builder import build_app  # noqa: E402
from jarvis.ui.web.server import create_app  # noqa: E402

KAREN = 'name: K.A.R.E.N.\ndescription: 정보 수집\npalette:\n  primary: "#97BC62"\ntools: [read_file]\n'


def _assembly(monkeypatch, tmp_path):
    team = tmp_path / "team"
    team.mkdir(exist_ok=True)
    (team / "karen.yaml").write_text(KAREN)
    monkeypatch.setenv("JARVIS_TEAM__DIR", str(team))
    monkeypatch.setenv("JARVIS_PROACTIVE__DAEMON_ENABLED", "false")
    monkeypatch.setenv("JARVIS_SCHEDULER__ENABLED", "false")
    monkeypatch.setenv("JARVIS_MEMORY__BACKEND", "in_memory")
    monkeypatch.setenv("JARVIS_SESSION__PERSISTENCE_BACKEND", "jsonl")
    monkeypatch.setenv("JARVIS_SESSION__SESSIONS_DIR", str(tmp_path / "sessions"))
    return build_app(JarvisSettings())


def _app(monkeypatch, tmp_path):
    return create_app(_assembly(monkeypatch, tmp_path), initial_session_id="default")


@pytest.fixture
def client(monkeypatch, tmp_path):
    with TestClient(_app(monkeypatch, tmp_path)) as c:
        yield c


def test_agents_lists_main_first_then_team(client):
    agents = client.get("/api/agents").json()["agents"]
    assert [a["id"] for a in agents] == ["main", "karen"]
    karen = agents[1]
    assert (karen["name"], karen["palette"]["primary"], karen["main"]) == ("K.A.R.E.N.", "#97BC62", False)
    assert "system_prompt" not in karen


def test_create_session_for_agent_and_list_shows_agent(client):
    resp = client.post("/api/sessions", json={"agent": "karen"})
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    assert resp.json()["agent"] == "karen"
    listed = client.get("/api/sessions").json()
    assert listed["agents"][sid] == "karen"
    assert listed["agents"]["default"] == "main"
    # 본문 없이 만들면 main
    plain = client.post("/api/sessions").json()
    assert plain["agent"] == "main"


def test_create_session_with_unknown_agent_is_400(client):
    resp = client.post("/api/sessions", json={"agent": "ghost"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "unknown agent: ghost"


def test_ws_opens_new_session_as_agent_and_ignores_agent_for_existing(client):
    with client.websocket_connect("/ws?session_id=kws&agent=karen") as ws:
        msg = ws.receive_json()
        assert msg["agent"]["id"] == "karen" and msg["agent"]["name"] == "K.A.R.E.N."
        assert msg["session_agents"]["kws"] == "karen"
    # 있는 세션은 저장된 에이전트로 열린다
    with client.websocket_connect("/ws?session_id=kws&agent=main") as ws:
        assert ws.receive_json()["agent"]["id"] == "karen"
    with client.websocket_connect("/ws?session_id=default") as ws:
        assert ws.receive_json()["agent"]["id"] == "main"


def test_ws_unknown_agent_closes_with_4404(client):
    with client.websocket_connect("/ws?session_id=gws&agent=ghost") as ws, pytest.raises(WebSocketDisconnect) as exc:
        ws.receive_json()
    assert exc.value.code == 4404


def test_branch_keeps_agent(client):
    sid = client.post("/api/sessions", json={"agent": "karen"}).json()["session_id"]
    branch = client.post(f"/api/sessions/{sid}/branch").json()["session_id"]
    assert client.get("/api/sessions").json()["agents"][branch] == "karen"


def test_session_reopens_as_its_agent_after_restart(monkeypatch, tmp_path):
    with TestClient(_app(monkeypatch, tmp_path)) as c:
        sid = c.post("/api/sessions", json={"agent": "karen"}).json()["session_id"]
    # 새 프로세스: 열린 세션 목록은 비지만 저장소의 에이전트로 다시 열린다
    with TestClient(_app(monkeypatch, tmp_path)) as c, c.websocket_connect(f"/ws?session_id={sid}") as ws:
        assert ws.receive_json()["agent"]["id"] == "karen"


def test_agenda_shows_every_agents_loops_with_agent(monkeypatch, tmp_path):
    import asyncio

    from jarvis.agent_layer.openloop import OpenLoop

    monkeypatch.setenv("JARVIS_THOUGHT__ENABLED", "true")
    monkeypatch.setenv("JARVIS_OPENLOOP__BACKEND", "in_memory")
    assembly = _assembly(monkeypatch, tmp_path)
    store = assembly.services.openloop_store
    asyncio.run(store.add(OpenLoop(description="뉴스 정리", origin_session="k1", agent_id="karen")))
    asyncio.run(store.add(OpenLoop(description="회의 준비", origin_session="default")))
    with TestClient(create_app(assembly, initial_session_id="default")) as c:
        loops = {lp["description"]: lp["agent"] for lp in c.get("/api/agenda").json()["open_loops"]}
    assert loops == {"뉴스 정리": "karen", "회의 준비": "main"}


def test_web_session_sandbox_uses_agent_approval_rules(monkeypatch, tmp_path):
    import asyncio

    monkeypatch.setenv("JARVIS_SECURITY__AGENT_APPROVALS_DIR", str(tmp_path / "approvals"))
    assembly = _assembly(monkeypatch, tmp_path)
    with TestClient(create_app(assembly, initial_session_id="default")):
        pass
    from jarvis.ui.web.session_registry import SessionRegistry

    registry = SessionRegistry(assembly.ctx, assembly.services, assembly.agents)
    _, sandbox = asyncio.run(registry.get_or_create("k-approve", "karen"))
    assert sandbox._rules is assembly.agents.approval_rules("karen")


def test_tools_are_scoped_to_session_agent(client):
    sid = client.post("/api/sessions", json={"agent": "karen"}).json()["session_id"]
    karen = [t["name"] for t in client.get(f"/api/tools?session_id={sid}").json()["tools"]]
    # 정의의 도구에 팀 대화 도구와 작업 패턴 저장 도구가 늘 붙는다
    assert karen == ["ask_agent", "read_file", "recall_episodes", "remember_task_pattern"]
    everything = [t["name"] for t in client.get("/api/tools").json()["tools"]]
    assert "bash" in everything and "bash" in [
        t["name"] for t in client.get("/api/tools?session_id=default").json()["tools"]
    ]
    # 열리지 않은 세션은 앱 전체
    assert [t["name"] for t in client.get("/api/tools?session_id=nope").json()["tools"]] == everything
