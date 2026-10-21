"""[core] 밖으로 보낼 것(먼저 건넨 말, 화면이 소리 내어 읽은 말)만 골라 알림 payload 로 바꾼다."""

from typing import Any
from collections.abc import Awaitable, Callable

from jarvis.agent_layer.types import AgentEvent, ProactiveMessageEvent
from jarvis.common.logger import get_logger
from jarvis.memory.scope import MAIN_AGENT

# filler 는 "잠깐만요" 류 대기 신호라 밖으로 내보낼 가치가 없다.
FORWARD_KINDS = frozenset({"proactive", "answer"})
# 화면이 읽은 말 중 서버가 이미 따로 보내는 것(🔔 은 proactive_payload, ⏰ 은 스케줄러). 다시 보내면 두 번 간다
SPOKEN_ELSEWHERE = frozenset({"proactive", "reminder"})

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


def spoken_payload(text: str, agent_id: str, source: str) -> dict[str, Any] | None:
    """화면이 소리 내어 읽은 말. source 는 화면이 붙인 종류(reply, filler, approval, phrase 등)다."""
    if not text.strip() or source in SPOKEN_ELSEWHERE:
        return None
    return {"type": "spoken", "agent": agent_id, "source": source, "text": text}


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
