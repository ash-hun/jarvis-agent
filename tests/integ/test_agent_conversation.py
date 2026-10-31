"""agent_conversation 기능: JARVIS 가 KAREN 에게 맡기고 KAREN 이 되묻는 대화가 에이전트 쌍 세션에 이어짐을 검증한다."""

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import reply_text, run_turn, scripted_env, use_provider, web_assembly, web_client  # noqa: E402
from jarvis.app.agent_conversation import PEER_REQUEST_RULE  # noqa: E402
from tests.fixtures.team_provider import TeamProvider  # noqa: E402

KAREN = (
    "name: K.A.R.E.N.\ndescription: 정보 수집\nsystem_prompt: 당신은 카렌입니다.\n"
    "tools: [read_file]\nproactive: false\n"
)
REQUEST = f"[J.A.R.V.I.S. 의 요청] AI 뉴스 3개를 찾아 줘\n({PEER_REQUEST_RULE})"


@pytest.fixture
def provider():
    yield from use_provider(TeamProvider())


@pytest.fixture
def assembly(monkeypatch, tmp_path, provider):
    (tmp_path / "team").mkdir()
    (tmp_path / "team" / "karen.yaml").write_text(KAREN)
    return web_assembly(monkeypatch, tmp_path, **scripted_env("team", tmp_path, tmp_path / "team"))


def test_jarvis_delegates_to_karen_who_asks_back(assembly, provider):
    with web_client(assembly) as client:
        with client.websocket_connect("/ws?session_id=default") as ws:
            hello = ws.receive_json()
            seen = run_turn(ws, "카렌에게 AI 뉴스 좀 물어봐")
        agents = client.get("/api/sessions").json()["agents"]
        karen_side = client.get("/api/sessions/peer-main-karen/messages").json()["messages"]
        # 앱을 닫을 때 세션 요약도 같은 프로바이더를 부르므로 닫기 전의 호출만 본다
        calls = list(provider.calls)

    assert hello["active_agents"] == []
    # 대화 순서: JARVIS 가 맡기고, KAREN 이 되묻고, JARVIS 가 답하고, KAREN 이 정리하고, JARVIS 가 정리한다
    assert calls == [
        ("main", "ask karen"),
        ("karen", "ask main back"),
        ("main", "answer karen"),
        ("karen", "summarize"),
        ("main", "summarize"),
    ]
    final = reply_text(seen)
    assert "K.A.R.E.N. 의 답" in final and "AI 반도체" in final
    # 두 에이전트가 함께 일한 구간이 HUD 에 알려졌다
    activity = [m["active"] for m in seen if m["type"] == "agent_activity"]
    assert ["main", "karen"] in activity
    assert activity[-1] == []
    # 에이전트 쌍마다 대화 세션이 남고, 세션 목록에 그 에이전트로 보인다
    assert agents["peer-main-karen"] == "karen"
    assert agents["peer-karen-main"] == "main"
    assert karen_side[0] == {"role": "user", "text": REQUEST}


def test_conversation_continues_in_same_peer_session(assembly, provider):
    with web_client(assembly) as client:
        with client.websocket_connect("/ws?session_id=default") as ws:
            ws.receive_json()
            run_turn(ws, "카렌에게 AI 뉴스 좀 물어봐")
            run_turn(ws, "카렌에게 한 번 더 물어봐")
        karen_side = client.get("/api/sessions/peer-main-karen/messages").json()["messages"]

    assert [m["text"] for m in karen_side if m["role"] == "user"] == [REQUEST, REQUEST]
