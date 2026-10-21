"""떠 있는 Web HUD 에서 에이전트마다 구체를 찍어 디스코드 아바타(assets/avatars/<id>.png)로 저장한다."""

# docker compose --profile web up -d
# uv run --with playwright --with pillow python scripts/capture_avatars.py main karen
# 그림을 바꿨으면 머지 뒤 JARVIS_NOTIFY__AVATAR_BASE_URL 을 그 커밋 경로로 바꾼다.
# 디스코드가 같은 주소의 옛 그림을 캐시한다

import io
import sys
from PIL import Image
from pathlib import Path
from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:7777"
OUT = Path(__file__).resolve().parents[1] / "assets" / "avatars"
SIZE = 512
# 구체 영역 중 가운데 이만큼만 쓴다. 바깥 링이 원 가장자리에 닿아야 40px 아바타에서도 색이 보인다
CROP = 0.86
SETTLE_MS = 4000  # 팔레트 전환과 idle 호흡이 가라앉을 때까지
MAIN = "main"


def shoot(page: Page, agent_id: str) -> None:
    page.wait_for_timeout(SETTLE_MS)
    box = page.locator(".sphere-wrap").bounding_box()
    assert box is not None, "구체를 찾지 못했다"
    side = min(box["width"], box["height"]) * CROP
    clip = {
        "x": box["x"] + (box["width"] - side) / 2,
        "y": box["y"] + (box["height"] - side) / 2,
        "width": side,
        "height": side,
    }
    image = Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("RGB")
    image.resize((SIZE, SIZE), Image.LANCZOS).save(OUT / f"{agent_id}.png", optimize=True)
    print(f"saved {OUT / f'{agent_id}.png'}")


def open_agent(page: Page, agent_id: str) -> str:
    """그 에이전트의 새 세션으로 화면을 바꾸고 세션 id 를 돌려준다."""
    sid: str = page.evaluate(
        """async (agent) => {
            const res = await fetch('/api/sessions', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                      body: JSON.stringify({agent})});
            const {session_id} = await res.json();
            (await import('/app/session.js')).connect(session_id);
            return session_id;
        }""",
        agent_id,
    )
    page.wait_for_function("a => document.documentElement.dataset.agent === a", arg=agent_id, timeout=20000)
    return sid


def close_session(page: Page, sid: str) -> None:
    # 열린 연결이 있으면 서버가 409 로 지우지 않는다. 기본 세션으로 돌아간 뒤 지운다
    page.evaluate("async () => (await import('/app/session.js')).connect('default')")
    page.wait_for_function("a => document.documentElement.dataset.agent === a", arg=MAIN, timeout=20000)
    page.wait_for_timeout(1000)
    status = page.evaluate(f"async () => (await fetch('/api/sessions/{sid}', {{method: 'DELETE'}})).status")
    print(f"temporary session {sid} deleted: HTTP {status}")


def main(agent_ids: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        page.goto(BASE)
        page.wait_for_selector("#sphere-gl")
        for agent_id in agent_ids:
            if agent_id == MAIN:
                shoot(page, MAIN)
                continue
            sid = open_agent(page, agent_id)
            shoot(page, agent_id)
            close_session(page, sid)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:] or [MAIN])
