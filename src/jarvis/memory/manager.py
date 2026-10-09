"""MemoryManager. 턴 전 변환(observe), 범위를 아는 조회(recall, recent), 쓰기 한 함수(remember), 공고화(consolidate)."""

import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from jarvis.memory.consolidation.compaction import Summarizer
from jarvis.memory.consolidation.semantic_extract import FactExtractor
from jarvis.memory.long_term.episodic import prepare_episode
from jarvis.memory.long_term.procedural import ProceduralSource, Procedure
from jarvis.memory.long_term.semantic import mark_interference, prepare_fact, supersede_conflicts
from jarvis.memory.retrieval.scoring import DEFAULT_PARAMS, ScoringParams, rank
from jarvis.memory.scope import LOCAL_USER, MemoryScope, current_scope, current_task, scope_from_context, task_scope
from jarvis.memory.stores.protocol import ItemStore
from jarvis.memory.types import MemoryItem, MemoryKind, Visibility
from jarvis.memory.working.in_memory import InMemoryWorkingStore
from jarvis.memory.working.state import WorkingState, WorkingStore
from jarvis.memory.working.window import apply_window, chars_of, cut_at_user_boundary, summary_message
from jarvis.model_layer.embeddings import Embedder
from jarvis.model_layer.types import Message, UserMessage

FACTS_HEADER = "[핵심 사실]"  # 고정 블록: 질의와 무관하게 항상 넣는 상위 의미 사실
LTM_HEADER = "[장기 기억]"  # 회상 블록: 이번 질의로 떠오른 항목
PROCEDURES_HEADER = "[절차 기억]"  # 질의가 가리키는 스킬
TASK_HEADER = "[작업 공유 메모리]"  # 같은 오케스트레이션 작업의 다른 에이전트가 남긴 결과
CONSOLIDATED = "consolidated"  # 의미 추출을 마친 일화에 남기는 metadata 키
CONSOLIDATABLE_SOURCES = frozenset({"session_end", "auto_summary", "manual_compact"})


@dataclass(frozen=True)
class WriteRule:
    kind: MemoryKind
    visibility: Visibility
    author: str | None  # None 이면 쓰는 에이전트의 id


# 쓰기 경로별 규칙. 계획서의 표가 정본이고 이 상수가 그 투영이다.
WRITE_RULES: dict[str, WriteRule] = {
    "explicit": WriteRule(MemoryKind.SEMANTIC, "shared", "user"),  # /remember
    "usermodel": WriteRule(MemoryKind.SEMANTIC, "shared", None),  # 사용자 모델 증류
    "extracted": WriteRule(MemoryKind.SEMANTIC, "shared", None),  # 일화에서 추출한 사실
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
        extractor: FactExtractor | None = None,
        procedures: ProceduralSource | None = None,
        threshold_chars: int = 80_000,
        keep_recent: int = 10,
        window_size: int = 50,
        inject_limit: int = 3,
        fixed_facts: int = 3,
        importance_threshold: float = 0.5,
        scoring: ScoringParams = DEFAULT_PARAMS,
        interference_threshold: float = 0.6,
        embedder: Embedder | None = None,
        min_similarity: float = 0.3,
    ) -> None:
        self._store = store
        self._working: WorkingStore = working or InMemoryWorkingStore()
        self._summarizer = summarizer
        self._extractor = extractor
        self._procedures = procedures
        self._threshold_chars = threshold_chars
        self._keep_recent = max(1, keep_recent)
        self._window_size = window_size
        self._inject_limit = inject_limit
        self._fixed_facts = fixed_facts
        self._importance_threshold = importance_threshold
        self._scoring = scoring
        self._interference_threshold = interference_threshold
        self._embedder = embedder
        self._min_similarity = min_similarity

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
        4. 고정 블록(상위 의미 사실), 회상 블록(질의로 떠오른 항목), 절차 힌트를 앞에 붙이며 되뇌기를 올린다.
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
        fixed = await self.fixed_facts(scope)
        recalled: list[MemoryItem] = []
        if query:
            recalled = await self.recall(query, scope, limit=self._inject_limit, exclude={i.id for i in fixed})
        procedures = self.procedures(query) if query else []

        blocks: list[Message] = []
        if fixed:
            blocks.append(_block(FACTS_HEADER, fixed))
        if recalled:
            blocks.append(_block(LTM_HEADER, recalled))
        if procedures:
            blocks.append(_procedures_block(procedures))
        shared_task = current_task.get()
        if shared_task is not None:
            notes = await self.task_notes(shared_task, scope)
            if notes:
                blocks.append(UserMessage(content=f"{TASK_HEADER}\n" + "\n".join(f"- {n}" for n in notes),
                                          timestamp=int(time.time() * 1000)))
        touched = fixed + recalled
        if touched:
            now = datetime.now()
            await self._store.touch([i.id for i in touched], now)
            for item in touched:
                state.rehearse(item.id)
            dirty = True

        if dirty:
            await self._working.save(state)
        return blocks + out

    async def fixed_facts(self, scope: MemoryScope | None = None) -> list[MemoryItem]:
        """질의와 무관하게 항상 넣는 의미 사실. 중요도와 최근성으로 고른다."""
        if self._fixed_facts <= 0:
            return []
        resolved = self.resolve_scope(scope)
        candidates = await self._store.recent(resolved, kinds=[MemoryKind.SEMANTIC], limit=self._fixed_facts * 4)
        # 고정 블록은 감쇠 없는 원값으로 고른다. 오래됐다고 핵심 사실이 밀리면 안 된다
        no_decay = replace(self._scoring, importance_half_life_hours=0.0)
        return rank(candidates, "", resolved, self._fixed_facts, params=no_decay)

    def procedures(self, query: str) -> list[Procedure]:
        return self._procedures.match(query) if self._procedures is not None else []

    # ── 작업 공유 메모리(오케스트레이션) ────────────────────────────────────

    async def share(self, root_task_id: str, text: str, author: str, scope: MemoryScope | None = None) -> None:
        """작업에 참여하는 에이전트 전원이 볼 메모를 남긴다. 블랙보드와 레벨 간 결과 전달이 이 통로를 쓴다."""
        await self.add_note(f"[{author}] {text}", scope=task_scope(self.resolve_scope(scope).user_id, root_task_id))

    async def task_notes(self, root_task_id: str, scope: MemoryScope | None = None) -> list[str]:
        state = await self._working.load(task_scope(self.resolve_scope(scope).user_id, root_task_id))
        return list(state.notes)

    async def clear_task(self, root_task_id: str, scope: MemoryScope | None = None) -> None:
        await self._working.clear(task_scope(self.resolve_scope(scope).user_id, root_task_id))

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
        """source 의 쓰기 규칙으로 항목을 만들어 저장한다. 키워드 인자는 규칙을 덮어쓴다.

        의미 항목은 같은 주제의 옛 사실을 대체하고, 일화 항목은 사건 시각을 받는다.
        """
        rule = WRITE_RULES.get(source, _DEFAULT_RULE)
        resolved = self.resolve_scope(scope)
        item = MemoryItem(
            content=content,
            kind=kind or rule.kind,
            scope=resolved,
            visibility=visibility or rule.visibility,
            author=author or rule.author or resolved.agent_id,
            source=source,
            tags=list(tags or []),
            metadata=dict(metadata or {}),
        )
        if importance is not None:
            item.importance = importance
        if item_id is not None:
            item.id = item_id
        if created_at is not None:
            item.created_at = created_at
        if item.kind is MemoryKind.SEMANTIC:
            prepare_fact(item)
        elif item.kind is MemoryKind.EPISODIC:
            prepare_episode(item)
        await self._embed(item)
        stored = await self._store.store(item)
        if item.kind is MemoryKind.SEMANTIC:
            await supersede_conflicts(self._store, item)
        return stored

    async def recall(
        self,
        query: str,
        scope: MemoryScope | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
        exclude: set[str] | None = None,
    ) -> list[MemoryItem]:
        """키워드와 의미 유사도로 후보를 넓게 모은 뒤 합성 점수로 상위 limit 개."""
        resolved = self.resolve_scope(scope)
        query_embedding = await self._embed_query(query)
        candidates = await self._store.search(
            query, resolved, kinds, limit * 4, query_embedding=query_embedding, min_similarity=self._min_similarity
        )
        if exclude:
            candidates = [c for c in candidates if c.id not in exclude]
        return rank(candidates, query, resolved, limit, params=self._scoring, query_embedding=query_embedding)

    async def _embed(self, item: MemoryItem) -> None:
        """임베더가 있으면 항목에 벡터를 붙인다. 임베딩 실패는 저장을 막지 않는다(키워드로는 여전히 찾힌다)."""
        if self._embedder is None:
            return
        try:
            item.embedding = (await self._embedder.embed([item.content]))[0]
            item.embedding_model = self._embedder.model
        except Exception:
            item.embedding, item.embedding_model = None, None

    async def _embed_query(self, query: str) -> list[float] | None:
        if self._embedder is None or not query.strip():
            return None
        try:
            return (await self._embedder.embed([query]))[0]
        except Exception:
            return None

    async def reembed(self, scope: MemoryScope | None = None, limit: int = 500) -> int:
        """벡터가 없거나 다른 모델로 만든 항목을 현재 임베더로 다시 임베딩한다. 돌려주는 값은 갱신 수.

        두 번 돌려도 같은 상태: 현재 모델로 된 항목은 건너뛴다.
        """
        if self._embedder is None:
            return 0
        resolved = self.resolve_scope(scope)
        items = await self._store.recent(resolved, limit=limit)
        stale = [i for i in items if i.embedding is None or i.embedding_model != self._embedder.model]
        if not stale:
            return 0
        vectors = await self._embedder.embed([i.content for i in stale])
        for item, vector in zip(stale, vectors, strict=True):
            item.embedding, item.embedding_model = vector, self._embedder.model
            await self._store.store(item)
        return len(stale)

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

    # ── 공고화 ──────────────────────────────────────────────────────────────

    async def consolidate(self, scope: MemoryScope | None = None) -> int:
        """세션 종료(와 나중엔 idle)에 부른다. 돌려주는 값은 새로 쓴 의미 사실 수.

        1. 아직 추출하지 않은 이 소유자의 일화(요약)에서 사실을 뽑아 shared 의미 항목으로 쓴다.
           importance 가 임계 미만이면 버린다. 같은 주제의 옛 사실은 remember 가 대체한다.
        2. 주제가 달라도 내용이 비슷한 의미 항목 쌍을 간섭 후보로 표시한다(대체는 하지 않는다).
        3. 작업 기억의 되뇌기 횟수를 항목의 rehearsal_count 로 옮기고 비운다.
        두 번 불러도 같은 상태: 추출한 일화와 간섭 쌍은 metadata 로 표시하고 되뇌기는 비운다.
        """
        resolved = self.resolve_scope(scope)
        written = 0
        if self._extractor is not None:
            episodes = await self._store.recent(resolved, kinds=[MemoryKind.EPISODIC], limit=50)
            for episode in episodes:
                if (
                    episode.source not in CONSOLIDATABLE_SOURCES
                    or episode.metadata.get(CONSOLIDATED)
                    or episode.scope.user_id != resolved.user_id
                    or episode.scope.agent_id != resolved.agent_id
                ):
                    continue
                facts = await self._extractor(episode.content)
                for fact in facts:
                    if fact.importance < self._importance_threshold:
                        continue
                    await self.remember(
                        fact.content,
                        source="extracted",
                        scope=resolved.with_session(None),
                        importance=fact.importance,
                        metadata={"from_episode": episode.id},
                    )
                    written += 1
                episode.metadata[CONSOLIDATED] = True
                await self._store.store(episode)

        await mark_interference(self._store, resolved.with_session(None), self._interference_threshold)

        state = await self._working.load(resolved)
        if state.rehearsal:
            for item_id, count in state.rehearsal.items():
                item = await self._store.get(item_id)
                if item is not None:
                    item.rehearsal_count += count
                    await self._store.store(item)
            state.rehearsal = {}
            await self._working.save(state)
        return written


def _last_user_text(messages: list[Message], max_chars: int = 200) -> str:
    for msg in reversed(messages):
        if msg.role != "user":
            continue
        if isinstance(msg.content, str):
            return msg.content[:max_chars]
        return "".join(getattr(b, "text", "") for b in msg.content)[:max_chars]
    return ""


def _block(header: str, items: list[MemoryItem]) -> UserMessage:
    body = "\n".join(f"- [{i.created_at.strftime('%Y-%m-%d')}] {i.content}" for i in items)
    return UserMessage(content=f"{header}\n{body}", timestamp=int(time.time() * 1000))


def _procedures_block(procedures: list[Procedure]) -> UserMessage:
    body = "\n".join(f"- /{p.name}: {p.description}".rstrip(": ") for p in procedures)
    return UserMessage(content=f"{PROCEDURES_HEADER}\n{body}", timestamp=int(time.time() * 1000))
