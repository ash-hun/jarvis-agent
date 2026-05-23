from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jarvis.model_layer.types import Message

if TYPE_CHECKING:
    from jarvis.agent_layer.memory.backends.protocol import STMBackend


class ShortTermMemory:
    """
    STMBackend를 감싸는 MemoryMiddleware.
    세션 범위 메시지 이력을 저장·조회한다.

    transform은 no-op — AgentSession의 run_agent_loop가 세션 컨텍스트를 직접 관리.
    store/retrieve/clear는 STMBackend에 위임.
    """

    def __init__(self, backend: STMBackend) -> None:
        self._backend = backend

    async def transform(
        self,
        messages: list[Message],
        context: dict[str, Any],
    ) -> list[Message]:
        return messages

    async def store(self, message: Message, context: dict[str, Any]) -> None:
        sid = context.get("session_id", "default")
        await self._backend.append(sid, message)

    async def retrieve(
        self,
        query: str,
        context: dict[str, Any],
        limit: int = 10,
    ) -> list[Message]:
        sid = context.get("session_id", "default")
        msgs = await self._backend.load(sid)
        return msgs[-limit:]

    async def clear(self, context: dict[str, Any]) -> None:
        sid = context.get("session_id", "default")
        await self._backend.clear(sid)
