"""MemoryManager. 턴 전 변환(observe), 범위를 아는 조회(recall, recent), 쓰기 한 함수(remember)."""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.memory.consolidation.compaction import Summarizer
from jarvis.memory.scope import LOCAL_USER, MemoryScope, current_scope, scope_from_context
from jarvis.memory.stores.protocol import ItemStore
from jarvis.memory.types import MemoryItem, MemoryKind, Visibility
from jarvis.memory.working.in_memory import InMemoryWorkingStore
from jarvis.memory.working.state import WorkingState, WorkingStore
from jarvis.memory.working.window import apply_window, chars_of, cut_at_user_boundary, summary_message
from jarvis.model_layer.types import Message, UserMessage

LTM_HEADER = "[장기 기억]"


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
    def __init__(
        self,
        store: ItemStore,
        working: WorkingStore | None = None,
        *,
        summarizer: Summarizer | None = None,
        threshold_chars: int = 80_000,
        keep_recent: int = 10,
        window_size: int = 50,
        inject_limit: int = 3,
    ) -> None:
        self._store = store
        self._working: WorkingStore = working or InMemoryWorkingStore()
        self._summarizer = summarizer
        self._threshold_chars = threshold_chars
        self._keep_recent = max(1, keep_recent)
        self._window_size = window_size
        self._inject_limit = inject_limit

    @property
    def store(self) -> ItemStore:
        return self._store

    @property
    def working(self) -> WorkingStore:
        return self._working

    def resolve_scope(self, scope: MemoryScope | None = None) -> MemoryScope:
        """명시 scope > 현재 턴의 contextvar > 로컬 사용자의 메인 범위."""
        return scope or current_scope.get() or MemoryScope(user_id=LOCAL_USER)

    # ── 턴 전 변환 ──────────────────────────────────────────────────────────

    async def observe(self, messages: list[Message], context: dict[str, Any]) -> list[Message]:
        """세션 이력 전체를 받아 LLM 에 넣을 컨텍스트를 만든다.

        1. 작업 기억의 요약이 덮는 앞부분을 버리고
        2. 남은 꼬리가 임계를 넘으면 한 번 더 요약해 persist 하고(임계를 다시 넘기 전엔 재요약 없음)
        3. 창 크기로 자르고
        4. 장기 기억 회상 블록을 앞에 붙이며 되뇌기 횟수를 올린다.
        """
        scope = scope_from_context(context)
        state = await self._working.load(scope)
        if state.summary_covers > len(messages):  # 이력이 줄었다(세션 초기화 등). 요약은 더 이상 맞지 않는다
            state = WorkingState(scope=scope)
        tail = messages[state.summary_covers :]
        dirty = False

        if (
            self._summarizer is not None
            and len(tail) > self._keep_recent
            and chars_of(tail, state.summary) > self._threshold_chars
        ):
            keep = cut_at_user_boundary(tail[-self._keep_recent :])
            to_compact = tail[: len(tail) - len(keep)]
            new_summary = await self._summarizer(to_compact, state.summary)
            if new_summary is not None:
                state.summary = new_summary
                state.summary_covers += len(to_compact)
                dirty = True
                await self.remember(new_summary, source="auto_summary", scope=scope)
                tail = keep

        tail = apply_window(tail, self._window_size)
        out: list[Message] = ([summary_message(state.summary)] if state.summary else []) + tail

        query = _last_user_text(messages)
        if query:
            items = await self.recall(query, scope, limit=self._inject_limit)
            if items:
                out = [_ltm_message(items), *out]
                for item in items:
                    state.rehearse(item.id)
                dirty = True

        if dirty:
            await self._working.save(state)
        return out

    async def add_note(self, text: str, scope: MemoryScope | None = None) -> None:
        resolved = self.resolve_scope(scope)
        state = await self._working.load(resolved)
        state.add_note(text)
        await self._working.save(state)

    async def working_state(self, scope: MemoryScope | None = None) -> WorkingState:
        return await self._working.load(self.resolve_scope(scope))

    async def clear_working(self, scope: MemoryScope | None = None) -> None:
        await self._working.clear(self.resolve_scope(scope))

    # ── 장기 기억 ───────────────────────────────────────────────────────────

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


def _last_user_text(messages: list[Message], max_chars: int = 200) -> str:
    for msg in reversed(messages):
        if msg.role != "user":
            continue
        if isinstance(msg.content, str):
            return msg.content[:max_chars]
        return "".join(getattr(b, "text", "") for b in msg.content)[:max_chars]
    return ""


def _ltm_message(items: list[MemoryItem]) -> UserMessage:
    body = "\n".join(f"- [{i.created_at.strftime('%Y-%m-%d')}] {i.content}" for i in items)
    return UserMessage(content=f"{LTM_HEADER}\n{body}", timestamp=int(time.time() * 1000))
