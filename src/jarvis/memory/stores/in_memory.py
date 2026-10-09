"""테스트와 in_memory 설정용 저장소. 프로세스가 끝나면 사라진다."""

from collections.abc import Sequence
from datetime import datetime

from jarvis.memory.scope import MemoryScope
from jarvis.memory.stores.protocol import tokens_of
from jarvis.memory.types import MemoryItem, MemoryKind
from jarvis.model_layer.embeddings import cosine


class InMemoryItemStore:
    def __init__(self) -> None:
        self._items: dict[str, MemoryItem] = {}

    async def store(self, item: MemoryItem) -> str:
        self._items[item.id] = item
        return item.id

    async def get(self, item_id: str) -> MemoryItem | None:
        return self._items.get(item_id)

    async def search(
        self,
        query: str,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
        query_embedding: list[float] | None = None,
        min_similarity: float = 0.3,
    ) -> list[MemoryItem]:
        tokens = tokens_of(query)
        if not tokens and query_embedding is None:
            return []
        hits = [
            i for i in self._visible(scope, kinds)
            if any(t in i.content.lower() for t in tokens)
            or (
                query_embedding is not None
                and i.embedding is not None
                and cosine(query_embedding, i.embedding) >= min_similarity
            )
        ]
        return _latest(hits, limit)

    async def recent(
        self,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return _latest(self._visible(scope, kinds), limit)

    async def touch(self, item_ids: Sequence[str], at: datetime) -> None:
        for item_id in item_ids:
            item = self._items.get(item_id)
            if item is not None:
                item.last_accessed = at

    async def supersede(self, old_id: str, new_id: str) -> None:
        old = self._items.get(old_id)
        if old is not None:
            old.superseded_by = new_id

    async def delete(self, item_id: str) -> None:
        self._items.pop(item_id, None)

    async def clear(self, scope: MemoryScope | None = None) -> None:
        if scope is None:
            self._items.clear()
            return
        for key in [k for k, i in self._items.items() if _same_owner(i.scope, scope)]:
            del self._items[key]

    def _visible(self, scope: MemoryScope, kinds: Sequence[MemoryKind] | None) -> list[MemoryItem]:
        allowed = set(kinds) if kinds else None
        return [
            i for i in self._items.values()
            if i.superseded_by is None
            and scope.can_read(i.scope, i.visibility)
            and (allowed is None or i.kind in allowed)
        ]


def _latest(items: list[MemoryItem], limit: int) -> list[MemoryItem]:
    return sorted(items, key=lambda i: i.created_at, reverse=True)[:limit]


def _same_owner(a: MemoryScope, b: MemoryScope) -> bool:
    return a.user_id == b.user_id and a.agent_id == b.agent_id
