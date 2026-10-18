"""두 최상위 에이전트가 서로 묻고 답하며 일하는 시나리오. JARVIS 가 KAREN 에게 맡기고, KAREN 이 JARVIS 에게 되묻는다."""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from jarvis.app.agent_conversation import PEER_REQUEST_RULE  # noqa: E402
from tests.fixtures.team_provider import TeamProvider  # noqa: E402
from jarvis.app.infra_builder import build_app  # noqa: E402
from jarvis.ui.web.server import create_app  # noqa: E402
from jarvis.config import JarvisSettings  # noqa: E402

KAREN = (
    "name: K.A.R.E.N.\ndescription: 정보 수집\nsystem_prompt: 당신은 카렌입니다.\n"
    "tools: [read_file]\nproactive: false\n"
)


@pytest.fixture
def provider():
    from jarvis.model_layer.registry import get_default_registry

    team = TeamProvider()
    registry = get_default_registry()
    registry._providers["team"] = team
    yield team
    registry._providers.pop("team", None)


@pytest.fixture
def assembly(monkeypatch, tmp_path, provider):
    (tmp_path / "team").mkdir()
    (tmp_path / "team" / "karen.yaml").write_text(KAREN)
    for key, value in {
        "JARVIS_TEAM__DIR": str(tmp_path / "team"),
        "JARVIS_LLM__PROVIDER": "team",
        "JARVIS_LLM__MODEL": "team-1",
        "JARVIS_THOUGHT__ENABLED": "false",
        "JARVIS_PROACTIVE__DAEMON_ENABLED": "false",
        "JARVIS_SCHEDULER__ENABLED": "false",
        "JARVIS_MEMORY__BACKEND": "in_memory",
        "JARVIS_SESSION__PERSISTENCE_BACKEND": "jsonl",
        "JARVIS_SESSION__SESSIONS_DIR": str(tmp_path / "sessions"),
        "JARVIS_SECURITY__AGENT_APPROVALS_DIR": str(tmp_path / "approvals"),
    }.items():
        monkeypatch.setenv(key, value)
    return build_app(JarvisSettings())


def _run_turn(ws, text):
    """루트 agent_end 까지 받은 메시지 전부.

    agent_end 직후에는 세션이 아직 바쁨 표시를 끄기 전일 수 있다. 그때 온 '처리 중' 오류면 잠깐 쉬고 다시 보낸다.
    """
    import time

    seen = []
    ws.send_json({"type": "user_message", "text": text})
    while True:
        msg = ws.receive_json()
        seen.append(msg)
        if msg["type"] == "agent_end":
            return seen
        if msg["type"] == "error" and "처리 중" in msg["message"]:
            time.sleep(0.1)
            ws.send_json({"type": "user_message", "text": text})


def test_jarvis_delegates_to_karen_who_asks_back(assembly, provider):
    with TestClient(create_app(assembly, initial_session_id="default")) as client:
        with client.websocket_connect("/ws?session_id=default") as ws:
            assert ws.receive_json()["active_agents"] == []
            seen = _run_turn(ws, "카렌에게 AI 뉴스 좀 물어봐")

        # 대화 순서: JARVIS 가 맡기고, KAREN 이 되묻고, JARVIS 가 답하고, KAREN 이 정리하고, JARVIS 가 정리한다
        assert provider.calls == [
            ("main", "ask karen"),
            ("karen", "ask main back"),
            ("main", "answer karen"),
            ("karen", "summarize"),
            ("main", "summarize"),
        ]
        final = "".join(m.get("text_delta", "") for m in seen if m["type"] == "message_update")
        assert "K.A.R.E.N. 의 답" in final and "AI 반도체" in final

        # 두 에이전트가 함께 일한 구간이 HUD 에 알려졌다
        activity = [m["active"] for m in seen if m["type"] == "agent_activity"]
        assert ["main", "karen"] in activity
        assert activity[-1] == []

        # 에이전트 쌍마다 대화 세션이 남고, 세션 목록에 그 에이전트로 보인다
        agents = client.get("/api/sessions").json()["agents"]
        assert agents["peer-main-karen"] == "karen"
        assert agents["peer-karen-main"] == "main"
        karen_side = client.get("/api/sessions/peer-main-karen/messages").json()["messages"]
        request = f"[J.A.R.V.I.S. 의 요청] AI 뉴스 3개를 찾아 줘\n({PEER_REQUEST_RULE})"
        assert karen_side[0] == {"role": "user", "text": request}


def test_conversation_continues_in_same_peer_session(assembly, provider):
    with TestClient(create_app(assembly, initial_session_id="default")) as client:
        with client.websocket_connect("/ws?session_id=default") as ws:
            ws.receive_json()
            _run_turn(ws, "카렌에게 AI 뉴스 좀 물어봐")
            _run_turn(ws, "카렌에게 한 번 더 물어봐")
        karen_side = client.get("/api/sessions/peer-main-karen/messages").json()["messages"]
        assert [m["text"] for m in karen_side if m["role"] == "user"] == [
            f"[J.A.R.V.I.S. 의 요청] AI 뉴스 3개를 찾아 줘\n({PEER_REQUEST_RULE})",
            f"[J.A.R.V.I.S. 의 요청] AI 뉴스 3개를 찾아 줘\n({PEER_REQUEST_RULE})",
        ]
