"""외부 알림 채널. 스케줄 결과와 proactive 발화를 열린 UI 밖(슬랙 등)으로도 보낸다."""

from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.core.notify.events import proactive_forwarder, proactive_payload
from jarvis.core.notify.slack import format_slack, slack_notifier

# 알림 payload 하나를 받아 어디론가 보내는 콜백. 스케줄러의 Notify 와 같은 모양이다.
Notify = Callable[[dict[str, Any]], Awaitable[None]]

# 설정의 kinds 이름 → payload["type"]. 사용자는 짧은 이름으로 고른다.
KIND_TYPES = {"reminder": "reminder", "proactive": "proactive_message"}


def fan_out(*notifiers: Notify | None) -> Notify:
    """여러 채널에 같은 payload 를 보낸다. 한 채널의 실패가 다른 채널을 막지 않는다."""
    targets = [n for n in notifiers if n is not None]

    async def notify(payload: dict[str, Any]) -> None:
        for target in targets:
            try:
                await target(payload)
            except Exception as exc:
                print(f"[Notify] channel failed: {exc!r}")

    return notify


def only_kinds(kinds: list[str], notify: Notify) -> Notify:
    """kinds 에 든 종류만 통과시킨다. 모르는 이름은 무시한다."""
    allowed = {KIND_TYPES[k] for k in kinds if k in KIND_TYPES}

    async def filtered(payload: dict[str, Any]) -> None:
        if payload.get("type") in allowed:
            await notify(payload)

    return filtered


__all__ = [
    "KIND_TYPES",
    "Notify",
    "fan_out",
    "format_slack",
    "only_kinds",
    "proactive_forwarder",
    "proactive_payload",
    "slack_notifier",
]
