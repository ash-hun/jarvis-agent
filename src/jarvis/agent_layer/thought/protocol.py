"""[agent_layer] inner thought 엔진 기본 클래스와 메모리 회상 콜백 타입을 정의한다."""

from typing import Any
from collections.abc import Awaitable, Callable

from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest
from jarvis.model_layer.types import Message

# 메모리 회상 콜백: `MemoryService.recall_messages` 시그니처와 호환.
RecallFn = Callable[[str, dict[str, Any], int], Awaitable[list[Message]]]


class ThoughtEngine:
    """
    inner thought 엔진의 교체 가능한 기본 클래스.

    그대로 쓰면 늘 None 을 돌려주는 "꺼진 엔진"이다. 기본 구현은 `InnerThoughtEngine`(별도 LLM 호출).
    고도화 시 이 클래스를 상속한 다른 엔진으로 통째 교체한다: 호출부(session.py)는 이 타입에만
    의존하므로 영향받지 않는다.
    """

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        """
        구조화된 사고 프레임을 생성한다.

        실패(파싱 오류·비활성·생략 조건)는 예외가 아니라 None으로 신호한다.
        inner thought는 부가 기능이므로 메인 턴을 절대 막지 않는다.
        """
        return None
