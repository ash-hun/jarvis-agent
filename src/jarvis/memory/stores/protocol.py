"""저장소 프로토콜. 조회는 scope 필수, 대체된(superseded) 항목은 기본적으로 제외한다."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from jarvis.memory.scope import MemoryScope
from jarvis.memory.types import MemoryItem, MemoryKind


@runtime_checkable
class ItemStore(Protocol):
    async def store(self, item: MemoryItem) -> str:
        """항목을 저장(같은 id 면 덮어쓰기)하고 id 를 돌려준다."""
        ...

    async def get(self, item_id: str) -> MemoryItem | None: ...

    async def search(
        self,
        query: str,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """scope 에서 보이는 항목 중 query 토큰과 겹치는 것을 최신순으로."""
        ...

    async def recent(
        self,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]: ...

    async def supersede(self, old_id: str, new_id: str) -> None:
        """old 를 new 로 대체했다고 표시한다. old 는 조회에서 빠지지만 지워지지 않는다."""
        ...

    async def delete(self, item_id: str) -> None: ...

    async def clear(self, scope: MemoryScope | None = None) -> None:
        """scope 가 있으면 그 (user, agent) 의 항목만, 없으면 전부 지운다."""
        ...


def tokens_of(query: str) -> list[str]:
    return [t.lower() for t in query.split() if t]
