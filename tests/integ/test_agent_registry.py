"""agent_registry 기능: 에이전트가 목록, 세션, ws, 도구, 승인 규칙, 브랜드로 이어지고 자율 행동은 ask 를 뺀다."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

pytest.importorskip("fastapi")

from starlette.websockets import WebSocketDisconnect  # noqa: E402

from jarvis.core.session import AUTONOMOUS_SAFE_TOOLS, AgentSession  # noqa: E402
from tests.fixtures.web_hud_helpers import web_assembly, web_client  # noqa: E402
from jarvis.core.proactive.proactive_types import ProactiveAction  # noqa: E402
from jarvis.core.policy.approval_rules import ApprovalRule  # noqa: E402
from jarvis.ui.web.session_registry import SessionRegistry  # noqa: E402
from jarvis.agent_layer.openloop import OpenLoop  # noqa: E402


KAREN = 'name: K.A.R.E.N.\ndescription: 정보 수집\npalette:\n  primary: "#97BC62"\ntools: [read_file]\n'


def _team_assembly(monkeypatch, tmp_path, **env):
    team = tmp_path / "team"
    team.mkdir(exist_ok=True)
    (team / "karen.yaml").write_text(KAREN)
    return web_assembly(monkeypatch, tmp_path, TEAM__DIR=str(team), **env)


@pytest.fixture
def client(monkeypatch, tmp_path):
    with web_client(_team_assembly(monkeypatch, tmp_path)) as c:
        yield c


def test_agents_lists_main_first_then_team(client):
    agents = client.get("/api/agents").json()["agents"]

    karen = agents[1]
    assert [a["id"] for a in agents] == ["main", "karen"]
    assert (karen["name"], karen["palette"]["primary"], karen["main"]) == ("K.A.R.E.N.", "#97BC62", False)
    assert "system_prompt" not in karen


def test_session_for_agent_is_listed_branched_and_scoped(client):
    resp = client.post("/api/sessions", json={"agent": "karen"})
    sid = resp.json()["session_id"]
    plain = client.post("/api/sessions").json()
    branch = client.post(f"/api/sessions/{sid}/branch").json()["session_id"]
    listed = client.get("/api/sessions").json()["agents"]
    karen_tools = [t["name"] for t in client.get(f"/api/tools?session_id={sid}").json()["tools"]]
    everything = [t["name"] for t in client.get("/api/tools").json()["tools"]]
    main_tools = [t["name"] for t in client.get("/api/tools?session_id=default").json()["tools"]]
    unopened = [t["name"] for t in client.get("/api/tools?session_id=nope").json()["tools"]]

    assert resp.status_code == 200 and resp.json()["agent"] == "karen"
    # 본문 없이 만들면 main
    assert plain["agent"] == "main"
    assert (listed[sid], listed["default"], listed[branch]) == ("karen", "main", "karen")
    # 정의의 도구에 팀 대화 도구와 작업 패턴 저장 도구가 늘 붙는다
    assert karen_tools == ["ask_agent", "read_file", "recall_episodes", "remember_task_pattern"]
    assert "bash" in everything and "bash" in main_tools
    # 열리지 않은 세션은 앱 전체
    assert unopened == everything


def test_ws_opens_new_session_as_agent_and_ignores_agent_for_existing(client):
    with client.websocket_connect("/ws?session_id=kws&agent=karen") as ws:
        first = ws.receive_json()
    # 있는 세션은 저장된 에이전트로 열린다
    with client.websocket_connect("/ws?session_id=kws&agent=main") as ws:
        again = ws.receive_json()
    with client.websocket_connect("/ws?session_id=default") as ws:
        default = ws.receive_json()

    assert first["agent"]["id"] == "karen" and first["agent"]["name"] == "K.A.R.E.N."
    assert first["session_agents"]["kws"] == "karen"
    assert again["agent"]["id"] == "karen"
    assert default["agent"]["id"] == "main"


def test_unknown_agent_is_refused_over_rest_and_ws(client):
    resp = client.post("/api/sessions", json={"agent": "ghost"})
    with client.websocket_connect("/ws?session_id=gws&agent=ghost") as ws, pytest.raises(WebSocketDisconnect) as exc:
        ws.receive_json()

    assert resp.status_code == 400
    assert resp.json()["error"] == "unknown agent: ghost"
    assert exc.value.code == 4404


def test_session_reopens_as_its_agent_after_restart(monkeypatch, tmp_path):
    with web_client(_team_assembly(monkeypatch, tmp_path)) as c:
        sid = c.post("/api/sessions", json={"agent": "karen"}).json()["session_id"]

    # 새 프로세스: 열린 세션 목록은 비지만 저장소의 에이전트로 다시 열린다
    with web_client(_team_assembly(monkeypatch, tmp_path)) as c, c.websocket_connect(f"/ws?session_id={sid}") as ws:
        hello = ws.receive_json()

    assert hello["agent"]["id"] == "karen"


def test_agenda_shows_every_agents_loops_with_agent(monkeypatch, tmp_path):
    assembly = _team_assembly(monkeypatch, tmp_path, THOUGHT__ENABLED="true", OPENLOOP__BACKEND="in_memory")
    store = assembly.services.openloop_store
    asyncio.run(store.add(OpenLoop(description="뉴스 정리", origin_session="k1", agent_id="karen")))
    asyncio.run(store.add(OpenLoop(description="회의 준비", origin_session="default")))

    with web_client(assembly) as c:
        loops = {lp["description"]: lp["agent"] for lp in c.get("/api/agenda").json()["open_loops"]}

    assert loops == {"뉴스 정리": "karen", "회의 준비": "main"}


def test_web_session_sandbox_uses_agent_approval_rules(monkeypatch, tmp_path):
    assembly = _team_assembly(monkeypatch, tmp_path, SECURITY__AGENT_APPROVALS_DIR=str(tmp_path / "approvals"))
    with web_client(assembly):
        pass
    assembly.agents.approval_rules("karen").add(ApprovalRule(tool="bash", pattern="ls"))
    registry = SessionRegistry(assembly.ctx, assembly.services, assembly.agents)

    _, karen = asyncio.run(registry.get_or_create("k-approve", "karen"))
    _, main = asyncio.run(registry.get_or_create("m-approve", "main"))

    # 승인 화면 없이도 karen 이 "항상 허용"한 명령은 karen 세션에서만 바로 통과한다
    assert asyncio.run(karen.decide("bash", {"command": "ls -la"})) == "allow"
    assert asyncio.run(main.decide("bash", {"command": "ls -la"})) == "deny"


def test_brand_js_and_manifest_carry_main_brand(client):
    brand = client.get("/brand.js")
    manifest = client.get("/manifest.json").json()

    assert brand.status_code == 200
    assert brand.headers["content-type"].startswith("application/javascript")
    assert brand.headers["cache-control"] == "no-cache"
    assert '"name": "J.A.R.V.I.S."' in brand.text
    assert '"quote": "Proof the Heart"' in brand.text
    assert "setProperty('--primary'" in brand.text
    assert manifest["short_name"] == "J.A.R.V.I.S."
    assert manifest["theme_color"] == "#02060c"


async def test_autonomous_actions_skip_ask_tools():
    tool = sorted(AUTONOMOUS_SAFE_TOOLS)[0]
    session = AgentSession.__new__(AgentSession)
    session._ask_tools = frozenset({tool})
    session._security = MagicMock()
    session._security.sandbox.is_approval_required.return_value = False
    session._tool_registry = MagicMock()
    session._tool_registry.execute = AsyncMock()

    done = await session._execute_autonomous([ProactiveAction(kind="tool", tool_name=tool, description="d")])

    assert done == "" and not session._tool_registry.execute.called
