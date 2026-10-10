"""모션그래픽 영상 소재 — 떠 있는 Web HUD 를 녹화해 구체가 상태별로 도는 모습을 public/ 에 넣는다.

상태는 window.HUD.setState 로 바꾼다(idle → thinking → tool_running → speaking).
    uv run --with playwright python assets/hud-motion/capture_video.py
결과: public/hud_full.mp4 (1600x900), public/sphere.mp4 (구체 크롭 760x760)
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "public"
BASE = "http://localhost:7777"
SIZE = {"width": 1600, "height": 900}
STATES = [("idle", 4000), ("thinking", 4000), ("tool_running", 3000), ("speaking", 3000)]
# 1600x900 레이아웃에서 구체 링의 바깥 경계. 리액터는 가운데 열에 있다.
SPHERE_CROP = "760:760:420:40"


def record() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="hud-rec-"))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=SIZE, record_video_dir=str(tmp), record_video_size=SIZE)
        page = ctx.new_page()
        page.goto(BASE + "/")
        page.wait_for_function("() => !document.getElementById('chat-input').disabled", timeout=30000)
        page.wait_for_timeout(2000)
        for state, ms in STATES:
            page.evaluate("s => HUD.setState(s)", state)
            page.wait_for_timeout(ms)
        page.evaluate("() => HUD.setState('idle')")
        page.wait_for_timeout(500)
        ctx.close()
        browser.close()
    return next(tmp.glob("*.webm"))


def main() -> None:
    OUT.mkdir(exist_ok=True)
    webm = record()
    full = OUT / "hud_full.mp4"
    sphere = OUT / "sphere.mp4"
    # 녹화 첫 2초는 접속·히스토리 로딩이라 버린다
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-i", str(webm), "-an",
                    "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-r", "30", str(full)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(full), "-vf", f"crop={SPHERE_CROP}",
                    "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(sphere)], check=True)
    shutil.rmtree(webm.parent, ignore_errors=True)
    for f in (full, sphere):
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                             capture_output=True, text=True).stdout.strip()
        print(f"{f.name}: {float(dur):.1f}s, {f.stat().st_size / 1048576:.1f} MB")


if __name__ == "__main__":
    main()
