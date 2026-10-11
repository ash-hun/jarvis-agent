"""[agent_layer] 에이전트 하네스가 거치는 메모리 미들웨어의 기본 클래스(그대로 통과)를 정의한다."""

from __future__ import annotations

from typing import Any

from jarvis.model_layer.types import Message


class MemoryMiddleware:
    """
    메모리 미들웨어 기본 클래스. 각 구현체는 독립적이며 체인에서 순차 적용됨.
    그대로 쓰면 메시지를 바꾸지 않고 저장도 회상도 하지 않는 통과 단계다.
    Pi: transformContext 훅 패턴.
    """

    async def transform(
        self,
        messages: list[Message],
        context: dict[str, Any],
    ) -> list[Message]:
        return messages

    async def store(
        self,
        message: Message,
        context: dict[str, Any],
    ) -> None:
        return None

    async def retrieve(
        self,
        query: str,
        context: dict[str, Any],
        limit: int = 10,
    ) -> list[Message]:
        return []

    async def clear(self, context: dict[str, Any]) -> None:
        return None
