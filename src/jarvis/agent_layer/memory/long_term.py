from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from jarvis.model_layer.types import Message, UserMessage

if TYPE_CHECKING:
    from jarvis.agent_layer.memory.backends.protocol import LTMBackend


class LongTermMemory:
    """
    LTMBackend를 감싸는 MemoryMiddleware (세션 횡단).

    transform: 최신 user 메시지를 쿼리로 LTM 검색 → 관련 항목을 컨텍스트 앞에 주입.
    store: no-op — LTM은 /remember 명시적 명령으로만 저장.
    retrieve: LTMBackend.search()로 Message 목록 반환.
    clear: no-op — LTM은 세션 범위 밖.
    """

    def __init__(self, backend: LTMBackend, inject_limit: int = 3) -> None:
        self._backend = backend
        self._inject_limit = inject_limit

    async def transform(
        self,
        messages: list[Message],
        context: dict[str, Any],
    ) -> list[Message]:
        query = _extract_last_user_query(messages)
        if not query:
            return messages

        entries = await self._backend.search(query, limit=self._inject_limit)
        if not entries:
            return messages

        memory_text = "[장기 기억]\n" + "\n".join(
            f"- [{e.created_at.strftime('%Y-%m-%d')}] {e.content}" for e in entries
        )
        memory_msg = UserMessage(content=memory_text, timestamp=int(time.time() * 1000))
        return [memory_msg, *messages]

    async def store(self, message: Message, context: dict[str, Any]) -> None:
        pass

    async def retrieve(
        self,
        query: str,
        context: dict[str, Any],
        limit: int = 10,
    ) -> list[Message]:
        entries = await self._backend.search(query, limit=limit)
        return [
            UserMessage(
                content=e.content,
                timestamp=int(e.created_at.timestamp() * 1000),
            )
            for e in entries
        ]

    async def clear(self, context: dict[str, Any]) -> None:
        pass


def _extract_last_user_query(messages: list[Message], max_chars: int = 200) -> str:
    """메시지 목록에서 마지막 user 메시지의 텍스트를 추출한다."""
    for msg in reversed(messages):
        if msg.role != "user":
            continue
        content = msg.content
        if isinstance(content, str):
            return content[:max_chars]
        if isinstance(content, list):
            for block in content:
                if hasattr(block, "text") and isinstance(block.text, str):
                    return block.text[:max_chars]
    return ""
