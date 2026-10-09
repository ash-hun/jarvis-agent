"""슬랙 incoming webhook 으로 알림 payload 를 보낸다."""

from collections.abc import Awaitable, Callable
from typing import Any

TIMEOUT_SEC = 10.0
MAX_TEXT = 2800  # 슬랙 메시지 한도(약 3000자) 아래로 자른다

# (url, json body) -> HTTP 상태. 기본은 httpx. 테스트는 가짜를 넣는다.
Post = Callable[[str, dict[str, Any]], Awaitable[int]]


def format_slack(payload: dict[str, Any]) -> dict[str, Any]:
    """알림 payload → 슬랙 메시지 본문. 순수 함수."""
    kind = payload.get("type", "")
    if kind == "reminder":
        head = f"⏰ {payload.get('name', '')}".strip()
        body = str(payload.get("text", ""))
        if payload.get("error"):
            head += " (실패)"
    elif kind == "proactive_message":
        head = "💭 Jarvis"
        body = str(payload.get("text", ""))
    else:
        head = str(kind or "jarvis")
        body = str(payload.get("text", payload))
    text = f"*{head}*\n{body}" if body else f"*{head}*"
    return {"text": text[:MAX_TEXT]}


async def _httpx_post(url: str, body: dict[str, Any]) -> int:
    import httpx

    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        response = await client.post(url, json=body)
        return response.status_code


def slack_notifier(webhook_url: str, *, post: Post | None = None) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """# idempotent: 슬랙 webhook 엔 중복 제거 키가 없다, 재시도하지 않아 같은 알림이 두 번 가지 않는다(실패는 로그)"""
    send = post or _httpx_post

    async def notify(payload: dict[str, Any]) -> None:
        status = await send(webhook_url, format_slack(payload))
        if status >= 400:
            print(f"[Notify] slack webhook returned {status}")

    return notify
