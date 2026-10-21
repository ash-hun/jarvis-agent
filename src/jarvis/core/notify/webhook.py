"""[core] 알림 webhook 채널이 같이 쓰는 payload 해석(제목, 본문)과 JSON POST."""

from typing import Any
from collections.abc import Awaitable, Callable

TIMEOUT_SEC = 10.0

# (url, json body) -> HTTP 상태. 기본은 httpx. 테스트는 가짜를 넣는다.
Post = Callable[[str, dict[str, Any]], Awaitable[int]]


def headline(payload: dict[str, Any]) -> tuple[str, str]:
    """알림 payload → (제목, 본문). 순수 함수."""
    kind = payload.get("type", "")
    if kind == "reminder":
        # 화면과 같은 아이콘: 알림은 ⏰, 할 일을 실행한 작업 결과는 ⏱
        mark = "⏱" if payload.get("kind") == "task" else "⏰"
        head = f"{mark} {payload.get('label') or payload.get('name', '')}".strip()
        if payload.get("error"):
            head += " (실패)"
        return head, str(payload.get("text", ""))
    if kind == "proactive_message":
        # 뒤로 넘긴 작업의 답(answer)은 먼저 건넨 말과 구분해 보인다
        mark = "💬" if payload.get("kind") == "answer" else "💭"
        return f"{mark} {payload.get('agent_name') or 'Jarvis'}", str(payload.get("text", ""))
    if kind == "spoken":
        return f"🔊 {payload.get('agent_name') or 'Jarvis'}", str(payload.get("text", ""))
    return str(kind or "jarvis"), str(payload.get("text", payload))


async def post_json(url: str, body: dict[str, Any]) -> int:
    import httpx

    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        response = await client.post(url, json=body)
        return response.status_code
