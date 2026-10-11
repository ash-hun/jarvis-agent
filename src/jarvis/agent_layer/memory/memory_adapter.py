"""[agent_layer] 메모리 서비스(memory 층)를 에이전트 하네스의 MemoryMiddleware 체인에 꽂는 어댑터."""

from typing import Any

from jarvis.agent_layer.memory.protocol import MemoryMiddleware
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.scope import scope_from_context
from jarvis.model_layer.types import Message, UserMessage


class MemoryMiddlewareAdapter(MemoryMiddleware):
    def __init__(self, memory: MemoryService) -> None:
        self._memory = memory

    @property
    def memory(self) -> MemoryService:
        return self._memory

    async def transform(self, messages: list[Message], context: dict[str, Any]) -> list[Message]:
        return await self._memory.observe(messages, context)

    async def store(self, message: Message, context: dict[str, Any]) -> None:
        # 세션 이력은 session_repo 가 정본이다. 장기 기억 쓰기는 명시 경로(remember)로만 한다.
        return None

    async def retrieve(self, query: str, context: dict[str, Any], limit: int = 10) -> list[Message]:
        items = await self._memory.recall(query, scope_from_context(context), limit=limit)
        return [UserMessage(content=i.content, timestamp=int(i.created_at.timestamp() * 1000)) for i in items]

    async def clear(self, context: dict[str, Any]) -> None:
        await self._memory.clear_working(scope_from_context(context))
