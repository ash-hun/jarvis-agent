"""[core] 슬랙 incoming webhook 으로 알림 payload 를 보낸다."""

from typing import Any
from collections.abc import Awaitable, Callable

from jarvis.core.notify.webhook import Post, headline, post_json
from jarvis.common.logger import get_logger

MAX_TEXT = 2800  # 슬랙 메시지 한도(약 3000자) 아래로 자른다

logger = get_logger(__name__)


def format_slack(payload: dict[str, Any]) -> dict[str, Any]:
    """알림 payload → 슬랙 메시지 본문. 순수 함수."""
    head, body = headline(payload)
    text = f"*{head}*\n{body}" if body else f"*{head}*"
    return {"text": text[:MAX_TEXT]}


def slack_notifier(webhook_url: str, *, post: Post | None = None) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """# idempotent: 슬랙 webhook 엔 중복 제거 키가 없다, 재시도하지 않아 같은 알림이 두 번 가지 않는다(실패는 로그)"""
    send = post or post_json

    async def notify(payload: dict[str, Any]) -> None:
        status = await send(webhook_url, format_slack(payload))
        if status >= 400:
            logger.info(f"[Notify] slack webhook returned {status}")

    return notify
