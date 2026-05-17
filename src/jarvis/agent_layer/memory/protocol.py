from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from jarvis.model_layer.types import Message


@runtime_checkable
class MemoryMiddleware(Protocol):
    """
    메모리 미들웨어 Protocol.
    각 구현체는 독립적이며 체인에서 순차 적용됨.
    Pi: transformContext 훅 패턴.
    """

    async def transform(
        self,
        messages: list[Message],
        context: dict[str, Any],
    ) -> list[Message]: ...

    async def store(
        self,
        message: Message,
        context: dict[str, Any],
    ) -> None: ...

    async def retrieve(
        self,
        query: str,
        context: dict[str, Any],
        limit: int = 10,
    ) -> list[Message]: ...

    async def clear(self, context: dict[str, Any]) -> None: ...
