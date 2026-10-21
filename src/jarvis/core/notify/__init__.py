"""[core] 외부 알림 채널. 스케줄 결과와 proactive 발화를 열린 UI 밖(슬랙, 디스코드)으로도 보낸다."""

from typing import Any
from collections.abc import Awaitable, Callable

from jarvis.core.notify.events import proactive_forwarder, proactive_payload
from jarvis.core.notify.discord import discord_notifier, format_discord
from jarvis.core.notify.slack import format_slack, slack_notifier
from jarvis.common.logger import get_logger
from jarvis.memory.scope import MAIN_AGENT

# 알림 payload 하나를 받아 어디론가 보내는 콜백. 스케줄러의 Notify 와 같은 모양이다.
Notify = Callable[[dict[str, Any]], Awaitable[None]]

# 설정의 kinds 이름 → payload["type"]. 사용자는 짧은 이름으로 고른다.
KIND_TYPES: dict[str, str] = {"reminder": "reminder", "proactive": "proactive_message"}

logger = get_logger(__name__)


def fan_out(*notifiers: Notify | None) -> Notify:
    """여러 채널에 같은 payload 를 보낸다. 한 채널의 실패가 다른 채널을 막지 않는다."""
    targets = [n for n in notifiers if n is not None]

    async def notify(payload: dict[str, Any]) -> None:
        for target in targets:
            try:
                await target(payload)
            except Exception as exc:
                logger.info(f"[Notify] channel failed: {exc!r}")

    return notify


def with_agents(identities: dict[str, tuple[str, str]], notify: Notify) -> Notify:
    """payload 의 agent id 에 이름(agent_name)과 아바타 주소(agent_avatar)를 붙인다. 모르는 id 는 그대로 보낸다."""

    async def named(payload: dict[str, Any]) -> None:
        identity = identities.get(str(payload.get("agent") or MAIN_AGENT))
        if identity is not None:
            payload = {**payload, "agent_name": identity[0], "agent_avatar": identity[1]}
        await notify(payload)

    return named


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
    "discord_notifier",
    "fan_out",
    "format_discord",
    "format_slack",
    "only_kinds",
    "proactive_forwarder",
    "proactive_payload",
    "slack_notifier",
    "with_agents",
]
