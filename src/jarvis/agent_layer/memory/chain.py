from __future__ import annotations

from typing import Any

from jarvis.agent_layer.memory.protocol import MemoryMiddleware
from jarvis.model_layer.types import Message


class MemoryMiddlewareChain:
    """
    미들웨어 체인 — 각 stage를 순서대로 적용.
    store()는 모든 stage에 병렬 전파.
    Pi: middleware chain 패턴.
    """

    def __init__(self, stages: list[MemoryMiddleware]) -> None:
        self._stages = stages

    def add(self, stage: MemoryMiddleware) -> None:
        self._stages.append(stage)

    async def transform(
        self,
        messages: list[Message],
        context: dict[str, Any],
    ) -> list[Message]:
        for stage in self._stages:
            messages = await stage.transform(messages, context)
        return messages

    async def store(
        self,
        message: Message,
        context: dict[str, Any],
    ) -> None:
        import asyncio
        await asyncio.gather(*[stage.store(message, context) for stage in self._stages])

    async def retrieve(
        self,
        query: str,
        context: dict[str, Any],
        limit: int = 10,
    ) -> list[Message]:
        if not self._stages:
            return []
        # 마지막으로 등록된 영속성 stage에서 검색
        return await self._stages[-1].retrieve(query, context, limit)

    async def clear(self, context: dict[str, Any]) -> None:
        import asyncio
        await asyncio.gather(*[stage.clear(context) for stage in self._stages])
