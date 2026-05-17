from __future__ import annotations

from collections import deque
from typing import Any

from jarvis.model_layer.types import Message


class WindowMemory:
    """최근 N개 메시지만 LLM 컨텍스트에 전달. store/retrieve는 no-op."""

    def __init__(self, max_messages: int = 50) -> None:
        self._max = max_messages
        self._store: dict[str, deque[Message]] = {}

    async def transform(
        self,
        messages: list[Message],
        context: dict[str, Any],
    ) -> list[Message]:
        return messages[-self._max:] if len(messages) > self._max else messages

    async def store(self, message: Message, context: dict[str, Any]) -> None:
        sid = context.get("session_id", "default")
        if sid not in self._store:
            self._store[sid] = deque(maxlen=self._max)
        self._store[sid].append(message)

    async def retrieve(
        self,
        query: str,
        context: dict[str, Any],
        limit: int = 10,
    ) -> list[Message]:
        sid = context.get("session_id", "default")
        msgs = list(self._store.get(sid, []))
        return msgs[-limit:]

    async def clear(self, context: dict[str, Any]) -> None:
        sid = context.get("session_id", "default")
        self._store.pop(sid, None)
