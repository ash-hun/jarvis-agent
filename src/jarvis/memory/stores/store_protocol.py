"""[memory] 장기 기억 저장소 기반 클래스로, scope 필수 조회와 대체 항목 제외 규칙을 프로세스 메모리 dict 로 구현한다."""

import string
from datetime import datetime
from dataclasses import dataclass
from collections.abc import Sequence

from jarvis.memory.memory_types import MemoryItem, MemoryKind
from jarvis.model_layer.embeddings import cosine
from jarvis.memory.scope import MemoryScope
from jarvis.memory.access import Readable

# 긴 것부터 본다('에서' 를 '서' 보다 먼저). 떼고 남는 말이 MIN_STEM_CHARS 보다 짧으면 떼지 않는다(회의, 평가)
JOSA = (
    "에서는", "에게서", "으로는", "에서", "에게", "한테", "까지", "부터", "으로", "처럼", "보다", "이랑",
    "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만", "로", "랑",
)
MIN_STEM_CHARS = 2
# 토큰 앞뒤에서 떼는 문장부호. 붙어 있으면 '서울에서?' 의 조사를 못 떼고 '-' 하나가 모든 항목에 걸린다
EDGE_PUNCT = string.punctuation + "“”‘’「」『』《》〈〉…·"
TASK_TYPE = "task_type"  # 일화 metadata: 그 턴에서 처음 부른 도구, 도구가 없으면 chat
OUTCOME = "outcome"  # 일화 metadata: success | failure


@dataclass(frozen=True)
class ItemFilter:
    """검색 조건. 비운 칸은 조건이 아니다. 시각은 일화의 사건 시각(없으면 저장 시각)으로 본다."""

    exclude_sources: frozenset[str] = frozenset()
    task_type: str | None = None
    outcome: str | None = None
    since: datetime | None = None  # 이 시각 이상
    until: datetime | None = None  # 이 시각 미만

    def allows(self, item: MemoryItem) -> bool:
        at = item.occurred_at or item.created_at
        return (
            item.source not in self.exclude_sources
            and (self.task_type is None or item.metadata.get(TASK_TYPE) == self.task_type)
            and (self.outcome is None or item.metadata.get(OUTCOME) == self.outcome)
            and (self.since is None or at >= self.since)
            and (self.until is None or at < self.until)
        )


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
        readable: Readable | None = None,
        where: ItemFilter | None = None,
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
            i for i in self._visible(scope, kinds, readable)
            if (where is None or where.allows(i))
            and (
                any(t in i.search_text.lower() for t in tokens)
            or (
                query_embedding is not None
                and i.embedding is not None
                and cosine(query_embedding, i.embedding) >= min_similarity
                )
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
        readable: Readable | None = None,
        where: ItemFilter | None = None,
    ) -> list[MemoryItem]:
        visible = self._visible(scope, kinds, readable)
        return _latest([i for i in visible if where is None or where.allows(i)], limit)

    async def important(
        self,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
        readable: Readable | None = None,
    ) -> list[MemoryItem]:
        """저장된 importance 내림차순(같으면 최신순). 질의 없이 고르는 고정 블록의 후보."""
        return _most_important(self._visible(scope, kinds, readable), limit)

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

    async def delete_sessions(self, prefixes: tuple[str, ...], dry_run: bool = False) -> int:
        """세션 id 가 이 접두어로 시작하는 항목을 지우고 수를 돌려준다. dry_run 이면 세기만 한다."""
        doomed = [k for k, i in self._items.items() if prefixes and (i.scope.session_id or "").startswith(prefixes)]
        if not dry_run:
            for key in doomed:
                del self._items[key]
        return len(doomed)

    async def delete_session(self, session_id: str) -> int:
        """세션 id 가 정확히 같은 항목만 지우고 수를 돌려준다. 세션에 묶이지 않은 항목(사용자 프로필)은 남는다."""
        doomed = [k for k, i in self._items.items() if i.scope.session_id == session_id]
        for key in doomed:
            del self._items[key]
        return len(doomed)

    async def clear(self, scope: MemoryScope | None = None) -> None:
        """scope 가 있으면 그 (user, agent) 의 항목만, 없으면 전부 지운다."""
        if scope is None:
            self._items.clear()
            return
        for key in [k for k, i in self._items.items() if _same_owner(i.scope, scope)]:
            del self._items[key]

    def _visible(
        self, scope: MemoryScope, kinds: Sequence[MemoryKind] | None, readable: Readable | None
    ) -> list[MemoryItem]:
        """사용자 경계를 먼저 보고, 그 안에서 층별 정책(readable, 없으면 자기 것만)으로 거른다."""
        allowed = set(kinds) if kinds else None
        policy = readable or Readable.own(scope.agent_id)
        return [
            i for i in self._items.values()
            if i.superseded_by is None
            and (i.scope.user_id is None or i.scope.user_id == scope.user_id)
            and policy.allows(i.scope.agent_id, i.kind)
            and (allowed is None or i.kind in allowed)
        ]


def tokens_of(query: str) -> list[str]:
    """공백 토큰의 앞뒤 문장부호를 떼고 소문자로 바꾼 뒤 끝의 한국어 조사를 뗀다.

    '서울에서' 는 '거주지: 서울' 의 부분 문자열이 아니다.
    """
    return [_strip_josa(t) for t in (w.strip(EDGE_PUNCT).lower() for w in query.split()) if t]


def _strip_josa(token: str) -> str:
    # ponytail: 조사 목록 휴리스틱('~도' 로 끝나는 명사를 자른다, 중요도 → 중요), 실데이터에서 명사를 자른
    # 비율은 0.02% 였다. 그 비율이 늘거나 잘린 말이 엉뚱한 기억을 끌어오면 형태소 분석기로 바꾼다
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
