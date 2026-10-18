"""[memory] 장기 기억 저장소 기반 클래스로, scope 필수 조회와 대체 항목 제외 규칙을 프로세스 메모리 dict 로 구현한다."""

from collections.abc import Sequence
from datetime import datetime

from jarvis.memory.scope import MemoryScope
from jarvis.memory.types import MemoryItem, MemoryKind
from jarvis.model_layer.embeddings import cosine

# 긴 것부터 본다('에서' 를 '서' 보다 먼저). 떼고 남는 말이 MIN_STEM_CHARS 보다 짧으면 떼지 않는다(회의, 평가)
JOSA = (
    "에서는", "에게서", "으로는", "에서", "에게", "한테", "까지", "부터", "으로", "처럼", "보다", "이랑",
    "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만", "로", "랑",
)
MIN_STEM_CHARS = 2


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

        후보는 최신순, 중요도순, 벡터 거리순으로 각각 limit 개씩 모은 합집합이다(최대 3 * limit).
        최신순 하나로만 자르면 오래됐지만 중요하거나 가장 가까운 항목이 점수를 받기도 전에 빠진다.
        순서는 의미가 없고 순위는 retrieval.rank 가 매긴다.
        """
        tokens = tokens_of(query)
        if not tokens and query_embedding is None:
            return []
        hits = [
            i for i in self._visible(scope, kinds)
            if any(t in i.search_text.lower() for t in tokens)
            or (
                query_embedding is not None
                and i.embedding is not None
                and cosine(query_embedding, i.embedding) >= min_similarity
            )
        ]
        nearest: list[MemoryItem] = []
        if query_embedding is not None:
            embedded = [i for i in hits if i.embedding is not None]
            nearest = sorted(embedded, key=lambda i: cosine(query_embedding, i.embedding or []), reverse=True)[:limit]
        return _union(_latest(hits, limit), _most_important(hits, limit), nearest)

    async def recent(
        self,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return _latest(self._visible(scope, kinds), limit)

    async def important(
        self,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """저장된 importance 내림차순(같으면 최신순). 질의 없이 고르는 고정 블록의 후보."""
        return _most_important(self._visible(scope, kinds), limit)

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
    """공백 토큰을 소문자로 바꾸고 끝의 한국어 조사를 뗀다. '서울에서' 는 '거주지: 서울' 의 부분 문자열이 아니다."""
    return [_strip_josa(t.lower()) for t in query.split() if t]


def _strip_josa(token: str) -> str:
    # ponytail: 조사 목록 휴리스틱(고양이 → 고양 처럼 넓게 잡힌다), 평가에서 오탐이 보이면 형태소 분석기로 바꾼다
    for josa in JOSA:
        if token.endswith(josa) and len(token) - len(josa) >= MIN_STEM_CHARS:
            return token[: -len(josa)]
    return token


def _latest(items: list[MemoryItem], limit: int) -> list[MemoryItem]:
    return sorted(items, key=lambda i: i.created_at, reverse=True)[:limit]


def _most_important(items: list[MemoryItem], limit: int) -> list[MemoryItem]:
    return sorted(items, key=lambda i: (i.importance, i.created_at), reverse=True)[:limit]


def _union(*groups: list[MemoryItem]) -> list[MemoryItem]:
    seen: dict[str, MemoryItem] = {}
    for group in groups:
        for item in group:
            seen.setdefault(item.id, item)
    return list(seen.values())


def _same_owner(a: MemoryScope, b: MemoryScope) -> bool:
    return a.user_id == b.user_id and a.agent_id == b.agent_id
