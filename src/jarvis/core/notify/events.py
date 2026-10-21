"""[core] AgentEvent 흐름에서 밖으로 보낼 것(proactive 발화)만 골라 알림 payload 로 바꾼다."""

from typing import Any
from collections.abc import Awaitable, Callable

from jarvis.agent_layer.types import AgentEvent, ProactiveMessageEvent
from jarvis.common.logger import get_logger
from jarvis.memory.scope import MAIN_AGENT

# filler 는 "잠깐만요" 류 대기 신호라 밖으로 내보낼 가치가 없다.
FORWARD_KINDS = frozenset({"proactive", "answer"})

logger = get_logger(__name__)


def proactive_payload(event: AgentEvent, agent_id: str = MAIN_AGENT) -> dict[str, Any] | None:
    if not isinstance(event, ProactiveMessageEvent) or event.kind not in FORWARD_KINDS or not event.text.strip():
        return None
    return {
        "type": "proactive_message",
        "id": event.message_id,
        "session_id": event.session_id,
        "kind": event.kind,
        "agent": agent_id,
        "text": event.text,
    }


def proactive_forwarder(
    notify: Callable[[dict[str, Any]], Awaitable[None]], agent_id: str = MAIN_AGENT
) -> Callable[[AgentEvent], Awaitable[None]]:
    """session.subscribe 에 꽂는 리스너. 알림 실패가 에이전트 루프를 깨지 않는다."""

    async def listener(event: AgentEvent) -> None:
        payload = proactive_payload(event, agent_id)
        if payload is None:
            return
        try:
            await notify(payload)
        except Exception as exc:
            logger.info(f"[Notify] proactive forward failed: {exc!r}")

    return listener
