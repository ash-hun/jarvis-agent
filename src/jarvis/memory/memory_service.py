"""[memory] MemoryService 로 턴 전 변환(observe), 범위를 아는 조회(recall, recent), 쓰기(remember), 공고화를 맡는다."""

import time
import hashlib
from typing import Any
from datetime import datetime
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass, replace

from jarvis.memory.long_term.task_pattern import (
    SAVE_HINT,
    SAVE_HINT_HEADER,
    TASK_PATTERN_SOURCE,
    TaskPattern,
    best_matches,
    from_item,
    pattern_id,
    render_block,
    teaches,
)
from jarvis.memory.working.window import (
    apply_window,
    chars_of,
    cut_at_user_boundary,
    last_turns,
    summary_message,
    turn_starts,
)
from jarvis.memory.long_term.semantic import mark_interference, prepare_fact, supersede_conflicts
from jarvis.memory.retrieval.scoring import DEFAULT_PARAMS, ScoringParams, rank, relevance
from jarvis.memory.scope import MemoryScope, current_task, scope_from_context, task_scope
from jarvis.memory.stores.protocol import OUTCOME, TASK_TYPE, ItemFilter, ItemStore
from jarvis.memory.types import REFERENT, MemoryItem, MemoryKind, Visibility
from jarvis.memory.long_term.procedural import ProceduralSource, Procedure
from jarvis.memory.consolidation.semantic_extract import FactExtractor
from jarvis.memory.working.state import WorkingState, WorkingStore
from jarvis.memory.access import MemoryPolicy, Readable, resolve
from jarvis.memory.working.in_memory import InMemoryWorkingStore
from jarvis.memory.consolidation.compaction import Summarizer
from jarvis.memory.long_term.episodic import prepare_episode
from jarvis.model_layer.types import Message, UserMessage
from jarvis.memory.working.deixis import retrieval_query
from jarvis.model_layer.embeddings import Embedder

FACTS_HEADER = "[핵심 사실]"  # 고정 블록: 질의와 무관하게 항상 넣는 상위 의미 사실
LTM_HEADER = "[장기 기억]"  # 회상 블록: 이번 질의로 떠오른 항목
PROCEDURES_HEADER = "[절차 기억]"  # 질의가 가리키는 스킬
TASK_HEADER = "[작업 공유 메모리]"  # 같은 오케스트레이션 작업의 다른 에이전트가 남긴 결과
CONSOLIDATED = "consolidated"  # 의미 추출을 마친 일화에 남기는 metadata 키
TURN_SOURCE = "turn"  # 턴 끝에 남기는 EDM 일화
TURN_INDEX = "turn"  # 턴 일화 metadata 의 세션 안 턴 번호(1부터)
TURN_CHARS = 1000  # 턴 일화에 남기는 발화와 답의 최대 글자 수. 도구 결과는 남기지 않는다
# session_end, auto_summary 는 더 쓰지 않지만 운영 DB 에 아직 추출하지 않은 행이 남아 있다
CONSOLIDATABLE_SOURCES = frozenset({TURN_SOURCE, "session_end", "auto_summary", "manual_compact"})


@dataclass(frozen=True)
class WriteRule:
    kind: MemoryKind
    visibility: Visibility
    author: str | None  # None 이면 쓰는 에이전트의 id
    importance: float | None = None  # None 이면 MemoryItem 기본값


# 쓰기 경로별 규칙. 계획서의 표가 정본이고 이 상수가 그 투영이다.
WRITE_RULES: dict[str, WriteRule] = {
    # /remember. 사용자가 일부러 남기라고 한 것은 그 자체로 임팩트 신호다(섬광 기억 자리 대상)
    "explicit": WriteRule(MemoryKind.SEMANTIC, "shared", "user", importance=0.8),
    "usermodel": WriteRule(MemoryKind.SEMANTIC, "shared", None),  # 사용자 모델 증류
    "extracted": WriteRule(MemoryKind.SEMANTIC, "shared", None),  # 일화에서 추출한 사실
    "auto_summary": WriteRule(MemoryKind.EPISODIC, "private", None),  # 컴팩션
    "manual_compact": WriteRule(MemoryKind.EPISODIC, "private", None),  # /compact
    "session_end": WriteRule(MemoryKind.EPISODIC, "private", None),  # 세션 종료 요약
    TURN_SOURCE: WriteRule(MemoryKind.EPISODIC, "private", None),  # 턴 기록(STM 3턴 밖은 여기서 회상)
    "thought": WriteRule(MemoryKind.EPISODIC, "private", None),  # 사고 로그
    "journal": WriteRule(MemoryKind.EPISODIC, "private", None),  # 자기 성찰 저널
    "delegation": WriteRule(MemoryKind.EPISODIC, "private", "orchestrator"),  # 위임 기록
    # 블랙보드 결과. 에이전트가 한 일이라 사용자 프로필(의미 기억)이 아니다. 다른 에이전트도 읽는다
    "promoted": WriteRule(MemoryKind.EPISODIC, "shared", None),
    # 사용자가 알려 준 작업 방식. 그 에이전트만 본다(같은 말도 에이전트마다 하는 일이 다르다)
    TASK_PATTERN_SOURCE: WriteRule(MemoryKind.PROCEDURAL, "private", "user"),
}
# 한 턴에 넣는 작업 패턴 수와, 고를 때 보는 후보 수
PATTERN_INJECT_LIMIT = 2
PATTERN_SCAN_LIMIT = 100
# 일반 회상 블록은 일화와 사실만. 작업 패턴은 따로 고른다
RECALL_KINDS = (MemoryKind.EPISODIC, MemoryKind.SEMANTIC)
# 사고 로그는 매 턴 사용자 말을 다시 적어 같은 낱말로 턴 일화보다 많이, 더 최근에 걸린다. 회상 자리를 빼앗지 않게 뺀다
RECALL_FILTER = ItemFilter(exclude_sources=frozenset({"thought"}))
CHAT_TASK = "chat"  # 도구를 부르지 않은 턴의 task_type
# 떠올린 항목의 낱말이 답에 이만큼 나오면 답에 쓰였다고 보고 되뇌기로 센다
USED_OVERLAP = 0.5
# 규칙에 없는 경로는 에이전트가 겪은 일로 둔다. 의미 기억은 사용자에 대한 사실(사용자 프로필)이라 위 규칙으로만 쓴다
_DEFAULT_RULE = WriteRule(MemoryKind.EPISODIC, "private", None)


class MemoryService:
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
        policies: Mapping[str, MemoryPolicy] | None = None,
        stm_turns: int | None = None,
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
        # 에이전트 id 별 읽기 정책(team/<id>.yaml). 없는 에이전트는 자기 것만 읽는다
        self._policies: Mapping[str, MemoryPolicy] = policies or {}
        # 정하면 STM 은 최근 이 턴 수이고 컴팩션 대신 턴마다 EDM 에 쓴다. None 은 옛 창과 컴팩션(평가 store 대상)
        self._stm_turns = stm_turns
        # 이번 턴의 (턴 번호, 사용자 발화). reinforce 가 답과 묶어 EDM 에 쓴다
        self._pending_turn: dict[MemoryScope, tuple[int, str]] = {}
        # 이번 턴에 떠올린 항목. 답이 나오면 reinforce 가 꺼내 쓰였는지 본다. 턴 하나 동안만 산다
        self._pending_recall: dict[MemoryScope, list[MemoryItem]] = {}

    @property
    def store(self) -> ItemStore:
        return self._store

    @property
    def working(self) -> WorkingStore:
        return self._working

    @property
    def summarizes_sessions(self) -> bool:
        """옛 창 모드만 세션 종료 요약을 쓴다. 턴 모드는 턴마다 EDM 에 이미 남겼다."""
        return self._stm_turns is None

    # ── 턴 전 변환 ──────────────────────────────────────────────────────────

    async def observe(self, messages: list[Message], context: dict[str, Any]) -> list[Message]:
        """세션 이력 전체를 받아 LLM 에 넣을 컨텍스트를 만든다.

        stm_turns 를 정했으면 최근 그 턴 수만 두고 블록을 붙인다. 이번 턴은 reinforce 가 EDM 에 쓴다.
        정하지 않았으면 옛 창이다.
        1. 작업 기억의 요약이 덮는 앞부분을 버리고
        2. 남은 꼬리가 임계를 넘으면 한 번 더 요약해 persist 하고(임계를 다시 넘기 전엔 재요약 없음)
        3. 창 크기로 자르고
        4. 고정 블록(상위 의미 사실), 회상 블록(질의로 떠오른 항목), 절차 힌트를 앞에 붙이며 되뇌기를 올린다.
        """
        scope = scope_from_context(context)
        if self._stm_turns is not None:
            starts = turn_starts(messages)
            if starts:
                self._pending_turn[scope] = (len(starts), _text_of(messages[starts[-1]]))
            # 창에 아직 있는 턴은 회상 블록에 다시 넣지 않는다
            first_in_window = max(1, len(starts) - self._stm_turns + 1)
            return await self._with_blocks(messages, last_turns(messages, self._stm_turns), scope, first_in_window)
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
        if dirty:
            await self._working.save(state)
        return await self._with_blocks(messages, out, scope, None)

    async def _with_blocks(
        self, messages: list[Message], out: list[Message], scope: MemoryScope, first_in_window: int | None
    ) -> list[Message]:
        """고정 블록, 회상 블록, 절차, 작업 패턴, 작업 공유 메모리를 창 앞에 붙이고 떠올린 항목을 기록한다."""
        query = _last_user_text(messages)
        # 지칭("그거 해줘")은 발화만으로 단서가 없다. 회상만 직전 대화를 덧붙인 질의로 찾는다
        cue = retrieval_query(messages)
        fixed = await self.fixed_facts(scope)
        fixed_ids = {i.id for i in fixed}
        cued: list[MemoryItem] = []
        recalled: list[MemoryItem] = []
        patterns: list[TaskPattern] = []
        if cue:
            # 고정 블록에 이미 있는 항목도 질의에 걸리면 떠올린 것이다. 회상 블록에는 겹치지 않게 뺀다
            # 창 안의 턴은 아래에서 빼므로 그만큼 더 받아야 회상 자리가 줄지 않는다
            extra = len(fixed) + (self._stm_turns or 0)
            cued = await self.recall(
                cue, scope, kinds=RECALL_KINDS, limit=self._inject_limit + extra, where=RECALL_FILTER
            )
            recalled = [
                i for i in cued if i.id not in fixed_ids and not _in_window(i, scope, first_in_window)
            ][: self._inject_limit]
            cued = [i for i in cued if i.id in fixed_ids] + recalled
            patterns = best_matches(await self.task_patterns(scope), cue, PATTERN_INJECT_LIMIT)
        procedures = self.procedures(query) if query else []

        blocks: list[Message] = []
        if fixed:
            blocks.append(_block(FACTS_HEADER, fixed))
        if recalled:
            blocks.append(_block(LTM_HEADER, recalled))
        if procedures:
            blocks.append(_procedures_block(procedures))
        if patterns:
            blocks.append(UserMessage(content=render_block(patterns), timestamp=int(time.time() * 1000)))
        if query and teaches(query):
            blocks.append(UserMessage(content=f"{SAVE_HINT_HEADER} {SAVE_HINT}", timestamp=int(time.time() * 1000)))
        shared_task = current_task.get()
        if shared_task is not None:
            notes = await self.task_notes(shared_task, scope)
            if notes:
                blocks.append(UserMessage(content=f"{TASK_HEADER}\n" + "\n".join(f"- {n}" for n in notes),
                                          timestamp=int(time.time() * 1000)))
        # 질의에 걸린 것만 후보로 둔다. 고정 블록에 들어갔다는 이유만으로 세면 한 번 고정된 사실이
        # 매 턴 스스로 강해지고 최근해져서 영영 자리를 내주지 않는다. 되뇌기는 답에 쓰인 것만 reinforce 가 센다
        self._pending_recall[scope] = cued
        if cued:
            await self._store.touch([i.id for i in cued], datetime.now())
        return blocks + out

    async def reinforce(
        self, answer: str, context: dict[str, Any], *, tools: Sequence[str] = (), failed: bool = False
    ) -> list[str]:
        """이번 턴에 떠올린 항목 중 답에 쓰인 것만 되뇌기로 센다. 두 번 불러도 한 번만 센다.

        턴 모드면 이번 턴을 EDM 에 쓴다. tools 는 이번 턴에 부른 도구 순서, failed 는 도구나 모델 실패.

        # ponytail: 항목 낱말이 답에 절반 넘게 나와야 쓰였다고 본다(긴 일화는 덜 잡힌다), 누락이 보이면 임베딩 유사도로
        """
        scope = scope_from_context(context)
        turn = self._pending_turn.pop(scope, None)
        if turn is not None:
            await self.record_turn(
                turn[0], turn[1], answer, scope, task_type=tools[0] if tools else CHAT_TASK, failed=failed, tools=tools
            )
        cued = self._pending_recall.pop(scope, [])
        used = [item.id for item in cued if answer and relevance(item.content, answer) >= USED_OVERLAP]
        if used:
            state = await self._working.load(scope)
            for item_id in used:
                state.rehearse(item_id)
            await self._working.save(state)
        return used

    async def record_turn(
        self,
        index: int,
        user: str,
        answer: str,
        scope: MemoryScope,
        *,
        task_type: str = CHAT_TASK,
        failed: bool = False,
        tools: Sequence[str] = (),
    ) -> str:
        """턴 하나를 EDM 일화로 쓴다. 같은 세션의 같은 턴 번호면 같은 항목을 덮어 두 번 불러도 하나다.

        # ponytail: 이력이 줄어 턴 번호를 1부터 다시 세면 옛 턴 일화를 덮는다, 세션 초기화가 잦아지면 세대 번호를 키에
        """
        key = f"{scope.user_id}|{scope.agent_id}|{scope.session_id}|{index}"
        content = f"사용자: {user[:TURN_CHARS]}\n답: {answer[:TURN_CHARS]}"
        return await self.remember(
            content, source=TURN_SOURCE, scope=scope,
            metadata={TURN_INDEX: index, TASK_TYPE: task_type, OUTCOME: "failure" if failed else "success",
                      "tools": list(dict.fromkeys(tools))},
            item_id="turn_" + hashlib.sha1(key.encode()).hexdigest()[:27],
        )

    async def fixed_facts(self, scope: MemoryScope) -> list[MemoryItem]:
        """질의와 무관하게 항상 넣는 의미 사실. 중요도와 최근성으로 고른다."""
        if self._fixed_facts <= 0:
            return []
        resolved = scope
        pool = self._fixed_facts * 4
        # 최신순으로만 고르면 의미 사실이 pool 개를 넘는 순간 오래된 핵심 사실(이름, 알레르기)이 후보에서 빠진다
        readable = self.readable(resolved)
        recent = await self._store.recent(resolved, kinds=[MemoryKind.SEMANTIC], limit=pool, readable=readable)
        important = await self._store.important(resolved, kinds=[MemoryKind.SEMANTIC], limit=pool, readable=readable)
        candidates = list({i.id: i for i in recent + important}.values())
        # 고정 블록은 감쇠 없는 원값으로 고른다. 오래됐다고 핵심 사실이 밀리면 안 된다
        no_decay = replace(self._scoring, importance_half_life_hours=0.0)
        return rank(candidates, "", resolved, self._fixed_facts, params=no_decay)

    # ── 작업 패턴(사용자가 알려 준 방식, 에이전트 전용) ─────────────────────────

    async def remember_pattern(self, pattern: TaskPattern, scope: MemoryScope) -> str:
        """같은 (사용자, 에이전트, 이름)이면 같은 항목을 덮는다. 다시 불러도 하나만 남는다."""
        resolved = scope.with_session(None)
        return await self.remember(
            pattern.content(), source=TASK_PATTERN_SOURCE, scope=resolved, metadata=pattern.metadata(),
            importance=0.8, item_id=pattern_id(resolved, pattern.name),
        )

    async def task_patterns(self, scope: MemoryScope) -> list[TaskPattern]:
        """이 에이전트가 받은 작업 패턴과, 정책의 pdm 이 허락한 에이전트의 패턴."""
        items = await self._store.recent(
            scope, kinds=[MemoryKind.PROCEDURAL], limit=PATTERN_SCAN_LIMIT, readable=self.readable(scope)
        )
        return [p for p in (from_item(i) for i in items) if p is not None]

    async def forget_pattern(self, name: str, scope: MemoryScope) -> bool:
        resolved = scope.with_session(None)
        item_id = pattern_id(resolved, name)
        if await self._store.get(item_id) is None:
            return False
        await self._store.delete(item_id)
        return True

    def procedures(self, query: str) -> list[Procedure]:
        return self._procedures.match(query) if self._procedures is not None else []

    # ── 작업 공유 메모리(오케스트레이션) ────────────────────────────────────

    async def share(self, root_task_id: str, text: str, author: str, scope: MemoryScope) -> None:
        """작업에 참여하는 에이전트 전원이 볼 메모를 남긴다. 블랙보드와 레벨 간 결과 전달이 이 통로를 쓴다."""
        await self.add_note(f"[{author}] {text}", scope=task_scope(scope.user_id, root_task_id))

    async def task_notes(self, root_task_id: str, scope: MemoryScope) -> list[str]:
        state = await self._working.load(task_scope(scope.user_id, root_task_id))
        return list(state.notes)

    async def clear_task(self, root_task_id: str, scope: MemoryScope) -> None:
        await self._working.clear(task_scope(scope.user_id, root_task_id))

    async def legacy_stm_rows(self) -> int | None:
        """옛 STM 테이블 행 수. 저장소가 모르면(in-memory) None."""
        return await self._working.legacy_stm_rows()

    async def drop_legacy_stm(self) -> None:
        await self._working.drop_legacy_stm()

    async def add_note(self, text: str, scope: MemoryScope) -> None:
        resolved = scope
        state = await self._working.load(resolved)
        state.add_note(text)
        await self._working.save(state)

    async def working_state(self, scope: MemoryScope) -> WorkingState:
        return await self._working.load(scope)

    async def clear_working(self, scope: MemoryScope) -> None:
        await self._working.clear(scope)

    async def forget_sessions(self, prefixes: tuple[str, ...], dry_run: bool = False) -> tuple[int, int]:
        """세션 id 접두어로 고른 세션의 장기 기억 항목과 작업 기억을 지운다. (항목 수, 작업 기억 수)."""
        return (await self._store.delete_sessions(prefixes, dry_run),
                await self._working.delete_sessions(prefixes, dry_run))

    # ── 장기 기억 ───────────────────────────────────────────────────────────

    async def remember(
        self,
        content: str,
        source: str,
        scope: MemoryScope,
        *,
        kind: MemoryKind | None = None,
        visibility: Visibility | None = None,
        author: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float | None = None,
        item_id: str | None = None,
        created_at: datetime | None = None,
        referent: str | None = None,
    ) -> str:
        """source 의 쓰기 규칙으로 항목을 만들어 저장한다. 키워드 인자는 규칙을 덮어쓴다.

        의미 항목은 같은 주제의 옛 사실을 대체하고, 일화 항목은 사건 시각을 받는다.
        referent 는 content 의 상대 지칭이 가리키는 대화다. 검색과 임베딩, 회상 표시에 같이 쓴다.
        """
        rule = WRITE_RULES.get(source, _DEFAULT_RULE)
        resolved = scope
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
        elif rule.importance is not None:
            item.importance = rule.importance
        if item_id is not None:
            item.id = item_id
        if referent:
            item.metadata[REFERENT] = referent
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
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
        exclude: set[str] | None = None,
        where: ItemFilter | None = None,
    ) -> list[MemoryItem]:
        """키워드와 의미 유사도로 후보를 넓게 모은 뒤 합성 점수로 상위 limit 개."""
        resolved = scope
        query_embedding = await self._embed_query(query)
        candidates = await self._store.search(
            query, resolved, kinds, limit * 4, query_embedding=query_embedding, min_similarity=self._min_similarity,
            readable=self.readable(resolved), where=where,
        )
        if exclude:
            candidates = [c for c in candidates if c.id not in exclude]
        return rank(candidates, query, resolved, limit, params=self._scoring, query_embedding=query_embedding)

    async def recall_episodes(
        self,
        query: str,
        scope: MemoryScope,
        *,
        task_type: str | None = None,
        outcome: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 5,
    ) -> list[MemoryItem]:
        """조건에 맞는 일화만 골라 회상한다(cherry-pick). 조건에 맞는 것이 없으면 비운다."""
        where = replace(RECALL_FILTER, task_type=task_type, outcome=outcome, since=since, until=until)
        return await self.recall(query, scope, kinds=[MemoryKind.EPISODIC], limit=limit, where=where)

    async def recall_messages(self, query: str, context: dict[str, Any], limit: int = 10) -> list[Message]:
        """inner thought 의 회상 콜백(RecallFn) 모양. 범위는 턴 컨텍스트에서 정하고 항목은 사용자 메시지로 감싼다."""
        items = await self.recall(query, scope_from_context(context), limit=limit)
        return [UserMessage(content=i.content, timestamp=int(i.created_at.timestamp() * 1000)) for i in items]

    async def _embed(self, item: MemoryItem) -> None:
        """임베더가 있으면 항목에 벡터를 붙인다. 임베딩 실패는 저장을 막지 않는다(키워드로는 여전히 찾힌다)."""
        if self._embedder is None:
            return
        try:
            item.embedding = (await self._embedder.embed([item.search_text]))[0]
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

    async def reembed(self, scope: MemoryScope, limit: int = 500) -> int:
        """벡터가 없거나 다른 모델로 만든 항목을 현재 임베더로 다시 임베딩한다. 돌려주는 값은 갱신 수.

        두 번 돌려도 같은 상태: 현재 모델로 된 항목은 건너뛴다.
        """
        if self._embedder is None:
            return 0
        resolved = scope
        items = await self._store.recent(resolved, limit=limit)
        stale = [i for i in items if i.embedding is None or i.embedding_model != self._embedder.model]
        if not stale:
            return 0
        vectors = await self._embedder.embed([i.search_text for i in stale])
        for item, vector in zip(stale, vectors, strict=True):
            item.embedding, item.embedding_model = vector, self._embedder.model
            await self._store.store(item)
        return len(stale)

    async def recent(
        self,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return await self._store.recent(scope, kinds, limit, readable=self.readable(scope))

    def readable(self, scope: MemoryScope) -> Readable:
        """이 범위의 에이전트가 층별로 읽을 수 있는 소유 에이전트. 저장소 조회는 전부 이 값으로 거른다."""
        return resolve(self._policies, scope.agent_id)

    async def get(self, item_id: str) -> MemoryItem | None:
        return await self._store.get(item_id)

    async def supersede(self, old_id: str, new_id: str) -> None:
        await self._store.supersede(old_id, new_id)

    async def forget(self, item_id: str) -> None:
        await self._store.delete(item_id)

    async def clear(self, scope: MemoryScope | None = None) -> None:
        await self._store.clear(scope)

    # ── 공고화 ──────────────────────────────────────────────────────────────

    async def consolidate(self, scope: MemoryScope) -> int:
        """세션 종료와 사용자가 조용한 daemon 틱에 부른다. 돌려주는 값은 새로 쓴 의미 사실 수.

        1. 아직 추출하지 않은 이 소유자의 일화(턴은 세션별 묶음, 요약은 하나씩)에서 사실을 뽑아 사용자 프로필로 쓴다.
           importance 가 임계 미만이면 버린다. 같은 주제의 옛 사실은 remember 가 대체한다.
        2. 주제가 달라도 내용이 비슷한 의미 항목 쌍을 간섭 후보로 표시한다(대체는 하지 않는다).
        3. 작업 기억의 되뇌기 횟수를 항목의 rehearsal_count 로 옮기고 비운다.
        두 번 불러도 같은 상태: 추출한 일화와 간섭 쌍은 metadata 로 표시하고 되뇌기는 비운다.
        """
        resolved = scope
        written = 0
        if self._extractor is not None:
            episodes = await self._store.recent(resolved, kinds=[MemoryKind.EPISODIC], limit=50)
            pending = [
                e for e in episodes
                if e.source in CONSOLIDATABLE_SOURCES
                and not e.metadata.get(CONSOLIDATED)
                and e.scope.user_id == resolved.user_id
                and e.scope.agent_id == resolved.agent_id
            ]
            for group in _extraction_groups(pending):
                facts = await self._extractor("\n\n".join(e.content for e in group))
                for fact in facts:
                    if fact.importance < self._importance_threshold:
                        continue
                    await self.remember(
                        fact.content,
                        source="extracted",
                        scope=resolved.with_session(None),
                        importance=fact.importance,
                        metadata={"from_episode": group[0].id},
                    )
                    written += 1
                # 추출 중에 죽으면 표시하지 않은 묶음은 다음 호출에서 다시 뽑는다. 같은 주제 사실은 remember 가 대체한다
                for episode in group:
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


def _extraction_groups(episodes: list[MemoryItem]) -> list[list[MemoryItem]]:
    """턴 일화는 세션별로 묶어 추출기를 한 번만 부른다. 요약 일화는 이미 세션 단위라 하나씩 둔다."""
    turns: dict[str | None, list[MemoryItem]] = {}
    groups: list[list[MemoryItem]] = []
    for episode in episodes:
        if episode.source == TURN_SOURCE:
            turns.setdefault(episode.scope.session_id, []).append(episode)
        else:
            groups.append([episode])
    for group in turns.values():
        group.sort(key=lambda e: int(e.metadata.get(TURN_INDEX, 0)))
        groups.append(group)
    return groups


def _text_of(message: Message) -> str:
    if isinstance(message.content, str):
        return message.content
    return message.text() if hasattr(message, "text") else ""


def _in_window(item: MemoryItem, scope: MemoryScope, first_in_window: int | None) -> bool:
    if first_in_window is None or item.source != TURN_SOURCE or item.scope.session_id != scope.session_id:
        return False
    return int(item.metadata.get(TURN_INDEX, 0)) >= first_in_window


def _last_user_text(messages: list[Message], max_chars: int = 200) -> str:
    for msg in reversed(messages):
        if msg.role != "user":
            continue
        if isinstance(msg.content, str):
            return msg.content[:max_chars]
        return "".join(getattr(b, "text", "") for b in msg.content)[:max_chars]
    return ""


def _block(header: str, items: list[MemoryItem]) -> UserMessage:
    body = "\n".join(f"- [{i.created_at.strftime('%Y-%m-%d')}] {i.content}{_referent_line(i)}" for i in items)
    return UserMessage(content=f"{header}\n{body}", timestamp=int(time.time() * 1000))


def _referent_line(item: MemoryItem) -> str:
    referent = item.metadata.get(REFERENT)
    if not referent:
        return ""
    return "\n  (가리킨 대화: " + " / ".join(line.strip() for line in str(referent).splitlines() if line.strip()) + ")"


def _procedures_block(procedures: list[Procedure]) -> UserMessage:
    # 설명이 없을 때만 "이름: " 꼬리를 뺀다. 설명 끝의 ":" 나 공백은 그대로 둔다
    body = "\n".join(f"- /{p.name}: {p.description}" if p.description else f"- /{p.name}" for p in procedures)
    return UserMessage(content=f"{PROCEDURES_HEADER}\n{body}", timestamp=int(time.time() * 1000))
