from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest
from jarvis.model_layer.types import Message

# 메모리 회상 콜백 — `MemoryMiddlewareChain.retrieve` 시그니처와 호환.
RecallFn = Callable[[str, dict[str, Any], int], Awaitable[list[Message]]]


@runtime_checkable
class ThoughtEngine(Protocol):
    """
    inner thought 엔진의 교체 가능한 계약.

    기본 구현은 `InnerThoughtEngine`(별도 LLM 호출). 고도화 시 이 Protocol을
    구현하는 다른 클래스로 통째 교체한다 — 호출부(session.py)는 Protocol에만
    의존하므로 영향받지 않는다.
    """

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        """
        구조화된 사고 프레임을 생성한다.

        실패(파싱 오류·비활성·생략 조건)는 예외가 아니라 None으로 신호한다 —
        inner thought는 부가 기능이므로 메인 턴을 절대 막지 않는다.
        """
        ...
