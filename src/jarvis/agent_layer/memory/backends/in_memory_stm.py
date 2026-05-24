from __future__ import annotations

from collections import defaultdict

from jarvis.model_layer.types import Message


class InMemorySTMBackend:
    """테스트·in_memory 환경용 STM 백엔드. 프로세스 재시작 시 데이터 소멸."""

    def __init__(self) -> None:
        self._store: dict[str, list[Message]] = defaultdict(list)

    async def load(self, session_id: str) -> list[Message]:
        return list(self._store[session_id])

    async def append(self, session_id: str, message: Message) -> None:
        self._store[session_id].append(message)

    async def clear(self, session_id: str) -> None:
        self._store[session_id] = []
