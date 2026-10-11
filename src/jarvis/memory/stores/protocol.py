"""[memory] 장기 기억 저장소 기반 클래스로, scope 필수 조회와 대체 항목 제외 규칙을 프로세스 메모리 dict 로 구현한다."""

from collections.abc import Sequence
from datetime import datetime

from jarvis.memory.scope import MemoryScope
from jarvis.memory.types import MemoryItem, MemoryKind
from jarvis.model_layer.embeddings import cosine


class ItemStore:
    """장기 기억 저장소. 기본 동작은 프로세스가 끝나면 사라지는 dict 이고, 영속 저장소는 메서드를 전부 덮어쓴다."""

    def __init__(self) -> None:
        self._items: dict[str, MemoryItem] = {}

    async def store(self, item: MemoryItem) -> str:
        """항목을 저장(같은 id 면 덮어쓰기)하고 id 를 돌려준다."""
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
        """scope 에서 보이는 항목 중 query 토큰과 겹치거나(키워드) 벡터가 min_similarity 이상 가까운 것(의미).

        둘의 합집합을 최신순으로 돌려준다. 순위는 retrieval.rank 가 다시 매긴다.
        """
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
        """회상된 항목의 last_accessed 를 갱신한다(점화)."""
        for item_id in item_ids:
            item = self._items.get(item_id)
            if item is not None:
                item.last_accessed = at

    async def supersede(self, old_id: str, new_id: str) -> None:
        """old 를 new 로 대체했다고 표시한다. old 는 조회에서 빠지지만 지워지지 않는다."""
        old = self._items.get(old_id)
        if old is not None:
            old.superseded_by = new_id

    async def delete(self, item_id: str) -> None:
        self._items.pop(item_id, None)

    async def clear(self, scope: MemoryScope | None = None) -> None:
        """scope 가 있으면 그 (user, agent) 의 항목만, 없으면 전부 지운다."""
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


def tokens_of(query: str) -> list[str]:
    return [t.lower() for t in query.split() if t]


def _latest(items: list[MemoryItem], limit: int) -> list[MemoryItem]:
    return sorted(items, key=lambda i: i.created_at, reverse=True)[:limit]


def _same_owner(a: MemoryScope, b: MemoryScope) -> bool:
    return a.user_id == b.user_id and a.agent_id == b.agent_id
