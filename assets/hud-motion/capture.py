"""모션그래픽 소재 — 떠 있는 Web HUD(localhost:7777)에서 상태별 화면을 찍어 public/ 에 넣는다.

서버 이벤트는 window.jarvisDebug.handleMessage 로 흉내 내므로 LLM 을 기다리지 않는다.
    uv run --with playwright python assets/hud-motion/capture.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "public"
BASE = "http://localhost:7777"
VIEWPORT = {"width": 1600, "height": 900}

PROACTIVE = "내일 10시 배포 결과 공유 전에, 열린 약속 세 개를 체크리스트로 묶어 둘까요?"
THOUGHT = "사용자는 내일 회의 준비를 챙기고 싶어 한다. 열린 약속이 세 개라 먼저 묶어 주는 편이 돕는 길이다."
ANSWER = (
    "배포 결과 공유를 **내일 오전 10시**로 기억해 두겠습니다.\n\n"
    "1. 회의 하루 전과 1시간 전에 알림\n"
    "2. 참석자 목록 확정\n"
    "3. 발표 범위 정리\n\n"
    "먼저 챙길 항목부터 말씀해 주세요."
)


def emit(page, payload):
    page.evaluate("m => jarvisDebug.handleMessage(m)", payload)


def shot(page, name):
    OUT.mkdir(exist_ok=True)
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("captured", name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
    page.goto(BASE + "/")
    page.wait_for_function("() => !document.getElementById('chat-input').disabled", timeout=30000)
    page.wait_for_timeout(2500)  # 구체 WebGL 이 자리 잡을 시간
    shot(page, "hud_idle")

    # 요청 → 💭 → 도구 실행 중
    page.fill("#chat-input", "내일 오전 10시에 팀에 배포 결과를 공유하기로 했어. 기억해줘")
    page.evaluate("() => { const t=document.getElementById('chat-input').value; "
                  "document.getElementById('chat-input').value=''; "
                  "jarvisDebug.handleMessage({type:'inner_thought', interpretation:%r, decision:'act', confidence:0.92}); }" % THOUGHT)
    emit(page, {"type": "agent_start"})
    emit(page, {"type": "tool_execution_start", "tool_call_id": "c1", "tool_name": "bash", "args": {"command": "echo done"}})
    page.wait_for_timeout(300)
    shot(page, "hud_tool")

    emit(page, {"type": "tool_execution_end", "tool_call_id": "c1", "is_error": False})
    emit(page, {"type": "stream_delta", "text": ANSWER})
    emit(page, {"type": "agent_end", "final_message": {"usage": {"input": 3900, "output": 420}}})
    page.wait_for_timeout(300)
    shot(page, "hud_answer")

    # 🔔 먼저 건넨 말 + 피드백 질문
    emit(page, {"type": "inner_thought", "interpretation": THOUGHT, "decision": "ask", "confidence": 0.88})
    emit(page, {"type": "proactive_message", "kind": "proactive", "message_id": "m1", "text": PROACTIVE})
    page.wait_for_timeout(300)
    shot(page, "hud_proactive")

    # 승인 모달
    emit(page, {"type": "approval_request", "id": "a1", "command": "echo hello", "reason": "bash 는 실행 전 승인이 필요합니다.", "always_pattern": "echo hello"})
    page.wait_for_timeout(300)
    shot(page, "hud_approval")
    browser.close()
