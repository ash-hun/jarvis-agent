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


# ── PWA 정적 자산 ─────────────────────────────────────────────────────────────


def test_manifest_is_served_with_required_fields(client):
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    manifest = resp.json()
    assert manifest["start_url"] == "./"
    assert manifest["display"] == "standalone"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])


def test_service_worker_is_served_and_skips_live_endpoints(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    body = resp.text
    # /ws·/api를 캐시하면 실시간 상태가 굳는다 — 우회 규칙이 반드시 남아 있어야 한다.
    assert "'/api'" in body and "'/ws'" in body


def test_icons_are_served(client):
    for name in ("icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        resp = client.get(f"/icons/{name}")
        assert resp.status_code == 200, name
        assert resp.content.startswith(b"\x89PNG")


def test_index_links_pwa_assets_and_registers_worker(client):
    html = client.get("/").text
    assert '<link rel="manifest" href="manifest.json">' in html
    assert 'name="theme-color"' in html
    assert "navigator.serviceWorker.register('sw.js')" in html
    assert "viewport-fit=cover" in html


def test_shell_precache_version_matches_asset_query(client):
    """sw.js가 프리캐시하는 URL과 index.html이 실제로 요청하는 URL이 어긋나면
    셸이 캐시되지 않은 채 오프라인에서 깨진다 — 버전 문자열을 함께 묶어 둔다."""
    import re

    sw = client.get("/sw.js").text
    html = client.get("/").text
    version = re.search(r"SHELL_VERSION = '(\d+)'", sw).group(1)
    assert f"app.js?v={version}" in html
    assert f"styles.css?v={version}" in html


# ── 브랜드 (에이전트별 이름·명언·색) ─────────────────────────────────────────


def test_brand_js_carries_settings_and_sets_css_vars(client):
    resp = client.get("/brand.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    assert resp.headers["cache-control"] == "no-cache"
    body = resp.text
    assert '"name": "J.A.R.V.I.S."' in body
    assert '"quote": "Proof the Heart"' in body
    assert "setProperty('--primary'" in body


def test_manifest_uses_brand_name_and_background(client):
    manifest = client.get("/manifest.json").json()
    assert manifest["short_name"] == "J.A.R.V.I.S."
    assert manifest["theme_color"] == "#02060c"


def test_brand_js_loads_before_hud_scripts(client):
    """brand.js가 hud.js보다 늦게 오면 리액터가 기본 색으로 그려진다."""
    html = client.get("/").text
    assert html.index('src="brand.js"') < html.index('src="hud.js')


# ── Agenda(스케줄 + open loops) / 도구 ───────────────────────────────────────


@pytest.fixture
def agenda(monkeypatch, tmp_path):
    """open loop 저장소는 메모리, 스케줄러는 루프 없이 tmp 디렉토리를 쓰는 서비스로 띄운다."""
    from unittest.mock import AsyncMock, MagicMock

    from jarvis.core.scheduler.service import SchedulerService
    from jarvis.core.scheduler.task import ScheduledTask

    monkeypatch.setenv("JARVIS_PROACTIVE__DAEMON_ENABLED", "false")
    monkeypatch.setenv("JARVIS_SCHEDULER__ENABLED", "false")
    monkeypatch.setenv("JARVIS_MEMORY__BACKEND", "in_memory")
    monkeypatch.setenv("JARVIS_SESSION__PERSISTENCE_BACKEND", "jsonl")
    monkeypatch.setenv("JARVIS_SESSION__SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("JARVIS_THOUGHT__ENABLED", "true")
    monkeypatch.setenv("JARVIS_OPENLOOP__BACKEND", "in_memory")
    settings = JarvisSettings()
    ctx, base_extra = _build_infra(settings)

    scheduler = SchedulerService(
        tasks=[
            ScheduledTask(name="late", schedule="0 23 * * *", prompt="late job"),
            ScheduledTask(name="off", schedule="0 9 * * *", prompt="off job", enabled=False),
        ],
        session_repo=MagicMock(),
        tool_registry=MagicMock(),
        model=MagicMock(),
        base_extra={},
        schedules_dir=str(tmp_path / "schedules"),
    )
    scheduler.start = AsyncMock()  # 실제 cron 루프는 돌리지 않는다
    ctx.scheduler = scheduler

    app = create_app(ctx, base_extra, initial_session_id="default")
    with TestClient(app) as c:
        yield c, base_extra["openloop_store"], scheduler


def test_agenda_lists_open_loops_and_schedules(agenda):
    import asyncio

    from jarvis.agent_layer.openloop.types import OpenLoop

    client, store, _ = agenda
    loop_id = asyncio.run(store.add(OpenLoop(description="리뷰 자료 보내기", origin_session="default")))

    body = client.get("/api/agenda").json()
    assert [lp["id"] for lp in body["open_loops"]] == [loop_id]
    assert body["open_loops"][0]["description"] == "리뷰 자료 보내기"
    names = [s["name"] for s in body["schedules"]]
    assert set(names) == {"late", "off"}
    # 꺼진 작업은 다음 실행이 없고 목록 아래로 간다
    off = next(s for s in body["schedules"] if s["name"] == "off")
    assert off["enabled"] is False and off["next_run"] is None
    assert names[-1] == "off"


def test_openloop_done_removes_it_from_agenda(agenda):
    import asyncio

    from jarvis.agent_layer.openloop.types import OpenLoop

    client, store, _ = agenda
    loop_id = asyncio.run(store.add(OpenLoop(description="x")))

    resp = client.post(f"/api/openloops/{loop_id}", json={"status": "done"})
    assert resp.status_code == 200
    assert client.get("/api/agenda").json()["open_loops"] == []


def test_openloop_rejects_bad_status_and_unknown_id(agenda):
    client, _, _ = agenda
    assert client.post("/api/openloops/nope", json={"status": "open"}).status_code == 400
    assert client.post("/api/openloops/nope", json={"status": "done"}).status_code == 404


def test_schedule_toggle(agenda):
    client, _, scheduler = agenda
    resp = client.post("/api/schedules/late", json={"enabled": False})
    assert resp.status_code == 200
    assert scheduler.get_task("late").enabled is False
    assert client.post("/api/schedules/late", json={"enabled": "no"}).status_code == 400
    assert client.post("/api/schedules/ghost", json={"enabled": True}).status_code == 404


def test_tools_list_marks_approval_required(client):
    tools = {t["name"]: t for t in client.get("/api/tools").json()["tools"]}
    assert tools["bash"]["approval"] is True
    assert tools["read_file"]["approval"] is False
