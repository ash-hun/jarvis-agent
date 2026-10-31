"""[core] 밖으로 보낼 것(먼저 건넨 말, 화면이 소리 내어 읽은 말)만 골라 알림 payload 로 바꾼다."""

from typing import Any
from collections.abc import Awaitable, Callable

from jarvis.agent_layer.session.session_protocol import TEST_SESSION_PREFIXES
from jarvis.agent_layer.agent_types import AgentEvent, ProactiveMessageEvent
from jarvis.common.logger import get_logger
from jarvis.memory.scope import MAIN_AGENT

# filler 는 "잠깐만요" 류 대기 신호라 밖으로 내보낼 가치가 없다.
FORWARD_KINDS = frozenset({"proactive", "answer"})
# 화면이 읽은 말 중 서버가 이미 따로 보내는 것(🔔 과 뒤로 넘긴 작업의 답은 proactive_payload, ⏰ 은 스케줄러).
# 다시 보내면 두 번 간다
SPOKEN_ELSEWHERE = frozenset({"proactive", "reminder", "answer"})

logger = get_logger(__name__)


def proactive_payload(event: AgentEvent, agent_id: str = MAIN_AGENT) -> dict[str, Any] | None:
    if not isinstance(event, ProactiveMessageEvent) or event.kind not in FORWARD_KINDS or not event.text.strip():
        return None
    if event.session_id.startswith(TEST_SESSION_PREFIXES):
        # 시험 세션의 말은 사용자 폰과 Discord 로 보내지 않는다(라이브 점검이 실제 푸시를 보냈다)
        return None
    return {
        "type": "proactive_message",
        "id": event.message_id,
        "session_id": event.session_id,
        "kind": event.kind,
        "agent": agent_id,
        "text": event.text,
    }


def spoken_notice_text(text: str, part: object, full_text: str) -> str:
    """화면이 글을 문장 조각(part 0, 1, ...)으로 나눠 읽게 하면 밖에는 첫 조각에서 원문 전체로 한 번만 알린다.

    나누지 않은 요청(part 없음)은 그 글 그대로, 둘째 조각부터는 빈 글(알리지 않음). 순수 함수.
    """
    if part is None:
        return text
    if part == 0:
        return full_text or text
    return ""


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
