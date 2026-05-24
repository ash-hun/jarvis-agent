from __future__ import annotations

from jarvis.agent_layer.memory.backends.protocol import MemoryEntry


class InMemoryLTMBackend:
    """테스트·in_memory 환경용 LTM 백엔드. 프로세스 재시작 시 데이터 소멸."""

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}

    async def store(self, entry: MemoryEntry) -> str:
        self._entries[entry.id] = entry
        return entry.id

    async def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        tokens = [t.lower() for t in query.split() if t]
        if not tokens:
            return []
        results = [
            e for e in self._entries.values()
            if any(t in e.content.lower() for t in tokens)
        ]
        results.sort(key=lambda e: e.created_at, reverse=True)
        return results[:limit]

    async def get_recent(self, limit: int = 10) -> list[MemoryEntry]:
        results = sorted(self._entries.values(), key=lambda e: e.created_at, reverse=True)
        return results[:limit]

    async def delete(self, entry_id: str) -> None:
        self._entries.pop(entry_id, None)

    async def clear_all(self) -> None:
        self._entries.clear()
