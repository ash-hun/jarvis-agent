"""Web HUD FastAPI 앱 — REST + WebSocket 엔드투엔드 명세.

faux provider + in_memory 백엔드(conftest 환경)로 실 API/DB 없이
create_app()을 띄워 라우트 배선을 검증한다. 가장 빈약했던 server.py 커버리지를 메운다.

fastapi가 없으면(web extra 미설치) 모듈 전체 skip."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from jarvis.config import JarvisSettings  # noqa: E402
from jarvis.ui.tui.startup import _build_infra  # noqa: E402
from jarvis.ui.web.server import create_app  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    """daemon/scheduler 백그라운드 루프를 끈 채 TestClient를 만든다(결정론적)."""
    monkeypatch.setenv("JARVIS_PROACTIVE__DAEMON_ENABLED", "false")
    monkeypatch.setenv("JARVIS_SCHEDULER__ENABLED", "false")
    # .env가 postgres 백엔드를 주입하므로 테스트에선 in_memory/jsonl로 강제(실 DB 불필요).
    monkeypatch.setenv("JARVIS_MEMORY__BACKEND", "in_memory")
    monkeypatch.setenv("JARVIS_SESSION__PERSISTENCE_BACKEND", "jsonl")
    monkeypatch.setenv("JARVIS_SESSION__SESSIONS_DIR", str(tmp_path / "sessions"))
    settings = JarvisSettings()
    ctx, base_extra = _build_infra(settings)
    app = create_app(ctx, base_extra, initial_session_id="default")
    with TestClient(app) as c:
        yield c


# ── REST ─────────────────────────────────────────────────────────────────────


def test_default_session_created_on_startup(client):
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert "default" in resp.json()["sessions"]


def test_create_session_returns_new_id(client):
    resp = client.post("/api/sessions")
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    assert sid and sid != "default"
    # 생성된 세션이 목록에 나타난다
    assert sid in client.get("/api/sessions").json()["sessions"]


def test_messages_empty_for_fresh_session(client):
    resp = client.get("/api/sessions/default/messages")
    assert resp.status_code == 200
    assert resp.json()["messages"] == []


def test_slash_commands_listed(client):
    resp = client.get("/api/slash-commands")
    assert resp.status_code == 200
    cmds = resp.json()["commands"]
    assert isinstance(cmds, list)
    # 디스패처가 배선됐다면 알려진 명령이 노출된다
    names = {c["name"] for c in cmds}
    assert names  # 비어있지 않음
    assert all("name" in c and "description" in c for c in cmds)


# ── WebSocket ──────────────────────────────────────────────────────────────────


def test_ws_connected_handshake(client):
    with client.websocket_connect("/ws?session_id=wstest") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        assert msg["session_id"] == "wstest"
        assert "model" in msg
        assert "voice" in msg
        assert msg["voice"]["stt_mode"] in {"browser", "server"}
        assert "slash_commands" in msg


def test_ws_session_appears_in_manager(client):
    with client.websocket_connect("/ws?session_id=wsnew") as ws:
        ws.receive_json()  # connected
    # WS 연결로 생성된 세션이 REST 목록에도 보인다
    assert "wsnew" in client.get("/api/sessions").json()["sessions"]


def test_ws_abort_is_noop_without_active_turn(client):
    """진행 중 턴이 없을 때 abort를 보내도 연결이 죽지 않는다."""
    with client.websocket_connect("/ws?session_id=wsabort") as ws:
        ws.receive_json()  # connected
        ws.send_json({"type": "abort"})
        # 후속 핸드셰이크가 깨지지 않았는지 확인 — 빈 user_message는 무시되고 루프 유지
        ws.send_json({"type": "user_message", "text": "   "})
        # 여기까지 예외 없이 도달하면 루프가 살아있는 것
