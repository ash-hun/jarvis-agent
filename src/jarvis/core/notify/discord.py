"""[core] 디스코드 채널 webhook 으로 알림 payload 를 보낸다."""

import re
from typing import Any
from collections.abc import Awaitable, Callable

from jarvis.core.notify.webhook import Post, headline, post_json
from jarvis.common.logger import get_logger

MAX_TEXT = 2000  # 디스코드 content 한도
MAX_USERNAME = 80  # 디스코드 webhook username 한도
# 모델이 쓴 글의 @everyone, @here, <@id> 가 사람을 부르지 않게 한다
NO_MENTIONS: dict[str, list[str]] = {"parse": []}
# allowed_mentions 를 보내도 @everyone 이 걸린 적이 있어 글에서도 끊는다. 폭 없는 공백은 화면에 보이지 않는다
_MENTION_RE = re.compile(r"@(?=everyone|here)|(?<=<)@")
ZERO_WIDTH = "\u200b"

logger = get_logger(__name__)


def format_discord(payload: dict[str, Any]) -> dict[str, Any]:
    """알림 payload → 디스코드 webhook 본문. 순수 함수."""
    head, body = headline(payload)
    text = f"**{head}**\n{body}" if body else f"**{head}**"
    text = _MENTION_RE.sub("@" + ZERO_WIDTH, text)
    message: dict[str, Any] = {"content": text[:MAX_TEXT], "allowed_mentions": NO_MENTIONS}
    # webhook 하나로 에이전트마다 다른 봇처럼 보이게 한다. 비우면 webhook 에 정해 둔 이름과 그림을 쓴다
    if payload.get("agent_name"):
        message["username"] = str(payload["agent_name"])[:MAX_USERNAME]
    if payload.get("agent_avatar"):
        message["avatar_url"] = str(payload["agent_avatar"])
    return message


def discord_notifier(webhook_url: str, *, post: Post | None = None) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """# idempotent: 디스코드 webhook 엔 중복 제거 키가 없다, 재시도하지 않아 같은 알림이 두 번 가지 않는다

    실패(429 포함)는 로그만 남긴다.
    """
    send = post or post_json

    async def notify(payload: dict[str, Any]) -> None:
        status = await send(webhook_url, format_discord(payload))
        if status >= 400:
            logger.info(f"[Notify] discord webhook returned {status}")

    return notify
