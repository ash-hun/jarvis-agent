"""MemoryManager. 모든 쓰기 경로가 거치는 한 함수(remember)와 범위를 아는 조회(recall, recent)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.memory.scope import LOCAL_USER, MemoryScope, current_scope
from jarvis.memory.stores.protocol import ItemStore
from jarvis.memory.types import MemoryItem, MemoryKind, Visibility


@dataclass(frozen=True)
class WriteRule:
    kind: MemoryKind
    visibility: Visibility
    author: str | None  # None 이면 쓰는 에이전트의 id


# 쓰기 경로별 규칙. 계획서의 표가 정본이고 이 상수가 그 투영이다.
WRITE_RULES: dict[str, WriteRule] = {
    "explicit": WriteRule(MemoryKind.SEMANTIC, "shared", "user"),  # /remember
    "usermodel": WriteRule(MemoryKind.SEMANTIC, "shared", None),  # 사용자 모델 증류
    "auto_summary": WriteRule(MemoryKind.EPISODIC, "private", None),  # 컴팩션
    "manual_compact": WriteRule(MemoryKind.EPISODIC, "private", None),  # /compact
    "session_end": WriteRule(MemoryKind.EPISODIC, "private", None),  # 세션 종료 요약
    "thought": WriteRule(MemoryKind.EPISODIC, "private", None),  # 사고 로그
    "journal": WriteRule(MemoryKind.EPISODIC, "private", None),  # 자기 성찰 저널
    "delegation": WriteRule(MemoryKind.EPISODIC, "private", "orchestrator"),  # 위임 기록
}
_DEFAULT_RULE = WriteRule(MemoryKind.SEMANTIC, "private", None)


class MemoryManager:
    def __init__(self, store: ItemStore) -> None:
        self._store = store

    @property
    def store(self) -> ItemStore:
        return self._store

    def resolve_scope(self, scope: MemoryScope | None = None) -> MemoryScope:
        """명시 scope > 현재 턴의 contextvar > 로컬 사용자의 메인 범위."""
        return scope or current_scope.get() or MemoryScope(user_id=LOCAL_USER)

    async def remember(
        self,
        content: str,
        source: str,
        scope: MemoryScope | None = None,
        *,
        kind: MemoryKind | None = None,
        visibility: Visibility | None = None,
        author: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float | None = None,
        item_id: str | None = None,
        created_at: datetime | None = None,
    ) -> str:
        """source 의 쓰기 규칙으로 항목을 만들어 저장한다. 키워드 인자는 규칙을 덮어쓴다."""
        rule = WRITE_RULES.get(source, _DEFAULT_RULE)
        resolved = self.resolve_scope(scope)
        item = MemoryItem(
            content=content,
            kind=kind or rule.kind,
            scope=resolved,
            visibility=visibility or rule.visibility,
            author=author or rule.author or resolved.agent_id,
            source=source,
            tags=tags or [],
            metadata=metadata or {},
        )
        if importance is not None:
            item.importance = importance
        if item_id is not None:
            item.id = item_id
        if created_at is not None:
            item.created_at = created_at
        return await self._store.store(item)

    async def recall(
        self,
        query: str,
        scope: MemoryScope | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return await self._store.search(query, self.resolve_scope(scope), kinds, limit)

    async def recent(
        self,
        scope: MemoryScope | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return await self._store.recent(self.resolve_scope(scope), kinds, limit)

    async def get(self, item_id: str) -> MemoryItem | None:
        return await self._store.get(item_id)

    async def supersede(self, old_id: str, new_id: str) -> None:
        await self._store.supersede(old_id, new_id)

    async def forget(self, item_id: str) -> None:
        await self._store.delete(item_id)

    async def clear(self, scope: MemoryScope | None = None) -> None:
        await self._store.clear(scope)
