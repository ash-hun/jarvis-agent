"""web_hud 기능: ws 접속 인사, 슬래시 명령 목록, 정적 셸과 PWA 자산(manifest, 서비스 워커, 아이콘)을 검증한다."""

import re
import pytest

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import web_assembly, web_client  # noqa: E402
from jarvis.ui.web.server import STATIC_DIR  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    with web_client(web_assembly(monkeypatch, tmp_path)) as c:
        yield c


def test_ws_connect_greets_with_session_model_voice_and_commands(client):
    with client.websocket_connect("/ws?session_id=wstest") as ws:
        msg = ws.receive_json()
    commands = client.get("/api/slash-commands")

    assert (msg["type"], msg["session_id"]) == ("connected", "wstest")
    assert "model" in msg and "slash_commands" in msg
    assert msg["voice"]["stt_mode"] in {"browser", "server"}
    assert commands.status_code == 200
    cmds = commands.json()["commands"]
    assert cmds and all("name" in c and "description" in c for c in cmds)


def test_ws_abort_is_noop_without_active_turn(client):
    """진행 중 턴이 없을 때 abort 를 보내도 연결이 죽지 않는다."""
    with client.websocket_connect("/ws?session_id=wsabort") as ws:
        ws.receive_json()
        ws.send_json({"type": "abort"})
        ws.send_json({"type": "user_message", "text": "   "})


def test_pwa_manifest_and_icons_are_served(client):
    manifest = client.get("/manifest.json").json()
    icons = {name: client.get(f"/icons/{name}") for name in ("icon-192.png", "icon-512.png", "apple-touch-icon.png")}

    assert manifest["start_url"] == "./"
    assert manifest["display"] == "standalone"
    assert {"192x192", "512x512"} <= {icon["sizes"] for icon in manifest["icons"]}
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])
    for name, resp in icons.items():
        assert resp.status_code == 200 and resp.content.startswith(b"\x89PNG"), name


def test_index_links_pwa_assets_and_loads_brand_first(client):
    html = client.get("/").text

    assert '<link rel="manifest" href="manifest.json">' in html
    assert 'name="theme-color"' in html
    assert "navigator.serviceWorker.register('sw.js')" in html
    assert "viewport-fit=cover" in html
    # brand.js 가 hud.js 보다 늦게 오면 리액터가 기본 색으로 그려진다
    assert html.index('src="brand.js"') < html.index('src="hud.js')


def test_service_worker_bypasses_live_endpoints_and_precaches_every_asset(client):
    sw = client.get("/sw.js")
    listed = set(re.findall(r"^\s*'([^']+\.(?:js|css))',", sw.text, re.M))
    on_disk = {
        str(p.relative_to(STATIC_DIR))
        for p in STATIC_DIR.rglob("*")
        if p.suffix in (".js", ".css") and p.name != "sw.js"
    }

    assert sw.status_code == 200
    # /ws, /api 를 캐시하면 실시간 상태가 굳는다
    assert "'/api'" in sw.text and "'/ws'" in sw.text
    # SHELL 목록이 디스크와 어긋나면 오프라인에서 셸이 깨진다. 모듈을 더하거나 지우면 목록 갱신을 강제한다
    assert listed == on_disk


def test_shell_assets_are_not_versioned_and_revalidate(client):
    """캐시 우선 + 수동 버전 대신 네트워크 우선 + no-cache. 버전 문자열이 생기면 HTML 과 CSS 가 섞인다."""
    html = client.get("/").text

    assert "?v=" not in html
    assert 'type="module" src="app/main.js"' in html
    assert "SHELL_VERSION" not in client.get("/sw.js").text
    for path in ("/", "/styles.css", "/app/main.js"):
        assert client.get(path).headers["cache-control"] == "no-cache", path
