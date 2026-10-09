"""MemoryManager: 쓰기 규칙, 범위 해석, 저장소 격리, LongTermMemory 미들웨어를 통한 상속."""

import pytest

from jarvis.memory import WRITE_RULES, MemoryKind, MemoryManager, MemoryScope, current_scope
from jarvis.memory.middleware import MemoryMiddlewareAdapter
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.stores.protocol import ItemStore
from jarvis.model_layer.types import UserMessage

U1_MAIN = MemoryScope(user_id="u1", agent_id="main", session_id="s1")
U1_RESEARCHER = MemoryScope(user_id="u1", agent_id="researcher", session_id="agent_researcher__s1")
U2_MAIN = MemoryScope(user_id="u2", agent_id="main", session_id="t1")


@pytest.fixture
def memory() -> MemoryManager:
    return MemoryManager(InMemoryItemStore())


# ── 쓰기 규칙 ────────────────────────────────────────────────────────────────


def test_store_satisfies_protocol():
    assert isinstance(InMemoryItemStore(), ItemStore)


async def test_remember_applies_write_rule_for_source(memory):
    item_id = await memory.remember("거주지: 서울", source="explicit", scope=U1_MAIN)
    item = await memory.get(item_id)
    assert item is not None
    assert (item.kind, item.visibility, item.author) == (MemoryKind.SEMANTIC, "shared", "user")

    summary_id = await memory.remember("요약", source="auto_summary", scope=U1_RESEARCHER)
    summary = await memory.get(summary_id)
    assert summary is not None
    assert (summary.kind, summary.visibility, summary.author) == (MemoryKind.EPISODIC, "private", "researcher")
    assert summary.session_id == "agent_researcher__s1"


async def test_remember_keyword_overrides_rule(memory):
    item_id = await memory.remember("x", source="explicit", scope=U1_MAIN, visibility="private", tags=["t"])
    item = await memory.get(item_id)
    assert item is not None and item.visibility == "private" and item.tags == ["t"]


def test_every_known_source_has_a_rule():
    assert {"explicit", "auto_summary", "manual_compact", "session_end", "thought", "journal"} <= set(WRITE_RULES)


# ── 범위 해석 ────────────────────────────────────────────────────────────────


async def test_resolve_scope_prefers_explicit_then_contextvar_then_local(memory):
    assert memory.resolve_scope(U2_MAIN) == U2_MAIN
    token = current_scope.set(U1_RESEARCHER)
    try:
        assert memory.resolve_scope() == U1_RESEARCHER
        assert memory.resolve_scope(U2_MAIN) == U2_MAIN
    finally:
        current_scope.reset(token)
    assert memory.resolve_scope() == MemoryScope(user_id="local")


# ── 저장소 격리 ──────────────────────────────────────────────────────────────


async def test_other_user_cannot_read_even_shared(memory):
    await memory.remember("생일: 3월 3일", source="explicit", scope=U1_MAIN)
    assert await memory.recall("생일", scope=U2_MAIN) == []
    assert await memory.recent(scope=U2_MAIN) == []


async def test_subagent_reads_user_shared_but_not_main_private(memory):
    await memory.remember("선호 음료: 커피", source="explicit", scope=U1_MAIN)  # shared
    await memory.remember("세션 요약: 예산 논의", source="auto_summary", scope=U1_MAIN)  # private

    seen = [i.content for i in await memory.recent(scope=U1_RESEARCHER)]
    assert seen == ["선호 음료: 커피"]


async def test_main_does_not_read_subagent_private(memory):
    await memory.remember("작업 메모: 논문 요약", source="auto_summary", scope=U1_RESEARCHER)
    assert await memory.recall("작업 메모", scope=U1_MAIN) == []
    # 같은 에이전트는 세션이 달라도 자기 private 항목을 본다
    other_session = U1_RESEARCHER.with_session("agent_researcher__s2")
    assert len(await memory.recall("작업 메모", scope=other_session)) == 1


async def test_legacy_global_items_are_visible_to_everyone(memory):
    legacy = MemoryScope(user_id=None, agent_id="main")
    await memory.remember("범위 도입 전 항목", source="explicit", scope=legacy)
    assert len(await memory.recall("항목", scope=U1_MAIN)) == 1
    assert len(await memory.recall("항목", scope=U2_MAIN)) == 1


async def test_superseded_items_drop_out_of_results(memory):
    old = await memory.remember("거주지: 서울", source="explicit", scope=U1_MAIN)
    new = await memory.remember("거주지: 부산", source="explicit", scope=U1_MAIN)
    await memory.supersede(old, new)
    assert [i.content for i in await memory.recall("거주지", scope=U1_MAIN)] == ["거주지: 부산"]
    assert (await memory.get(old)) is not None  # 지워지진 않는다


async def test_clear_with_scope_removes_only_that_owner(memory):
    await memory.remember("a", source="explicit", scope=U1_MAIN)
    await memory.remember("b", source="explicit", scope=U2_MAIN)
    await memory.clear(U1_MAIN)
    assert await memory.recent(scope=U1_MAIN) == []
    assert len(await memory.recent(scope=U2_MAIN)) == 1


# ── 미들웨어: harness context 에서 범위를 조립한다 ───────────────────────────


async def test_long_term_middleware_scopes_by_context(memory):
    await memory.remember("선호 음료: 커피", source="explicit", scope=U1_MAIN)
    await memory.remember("세션 요약: 예산 논의", source="auto_summary", scope=U1_MAIN)
    ltm = MemoryMiddlewareAdapter(MemoryManager(memory.store, inject_limit=5))
    msgs = [UserMessage(content="커피 그리고 예산 얘기", timestamp=0)]

    def injected(out: list) -> str:  # 고정 사실 블록 + 회상 블록(원 메시지 앞에 붙는다)
        return "\n".join(m.content for m in out[:-1])

    as_main = await ltm.transform(msgs, {"user_id": "u1", "agent_id": "main", "session_id": "s9"})
    assert "커피" in injected(as_main) and "예산" in injected(as_main)

    as_sub = await ltm.transform(msgs, {"user_id": "u1", "agent_id": "researcher", "session_id": "x"})
    assert "커피" in injected(as_sub) and "예산" not in injected(as_sub)

    as_other = await ltm.transform(msgs, {"user_id": "u2", "agent_id": "main"})
    assert as_other == msgs


async def test_middleware_without_user_in_context_falls_back_to_local(memory):
    await memory.remember("로컬 사용자 기억", source="explicit", scope=MemoryScope(user_id="local"))
    ltm = MemoryMiddlewareAdapter(memory)
    out = await ltm.transform([UserMessage(content="사용자 기억", timestamp=0)], {"session_id": "s"})
    assert "로컬 사용자 기억" in out[0].content


# ── 3단계: 의미 대체, 고정 블록, 절차 힌트, 공고화 ──────────────────────────


async def test_same_topic_fact_supersedes_older_one_on_write(memory):
    old = await memory.remember("거주지: 서울", source="explicit", scope=U1_MAIN)
    new = await memory.remember("거주지: 부산", source="explicit", scope=U1_MAIN)
    assert [i.content for i in await memory.recall("거주지", scope=U1_MAIN)] == ["거주지: 부산"]
    assert (await memory.get(old)).superseded_by == new
    assert "key:거주지" in (await memory.get(new)).tags


async def test_late_dated_fact_is_superseded_by_existing_newer_one(memory):
    from datetime import datetime

    newer = await memory.remember("거주지: 부산", source="explicit", scope=U1_MAIN, created_at=datetime(2026, 6, 1))
    late = await memory.remember("거주지: 서울", source="explicit", scope=U1_MAIN, created_at=datetime(2026, 1, 1))
    assert (await memory.get(late)).superseded_by == newer
    assert [i.content for i in await memory.recall("거주지", scope=U1_MAIN)] == ["거주지: 부산"]


async def test_supersede_stays_within_owner(memory):
    await memory.remember("거주지: 서울", source="explicit", scope=U1_MAIN)
    await memory.remember("거주지: 부산", source="explicit", scope=U2_MAIN)  # 다른 사용자
    assert [i.content for i in await memory.recall("거주지", scope=U1_MAIN)] == ["거주지: 서울"]


async def test_non_fact_text_is_never_superseded(memory):
    a = await memory.remember("회의가 길었다", source="explicit", scope=U1_MAIN)
    await memory.remember("회의가 짧았다", source="explicit", scope=U1_MAIN)
    assert (await memory.get(a)).superseded_by is None


async def test_episodes_get_occurred_at(memory):
    item_id = await memory.remember("요약", source="session_end", scope=U1_MAIN)
    item = await memory.get(item_id)
    assert item.occurred_at == item.created_at


async def test_fixed_facts_block_then_recall_block_then_procedures(memory):
    from jarvis.memory.long_term.procedural import InMemoryProcedures, Procedure
    from jarvis.model_layer.types import UserMessage

    procedures = InMemoryProcedures([Procedure(name="deploy", description="스테이징 배포", aliases=("배포",))])
    mgr = MemoryManager(memory.store, procedures=procedures, fixed_facts=1, inject_limit=3)
    await mgr.remember("거주지: 부산", source="explicit", scope=U1_MAIN, importance=0.9)
    await mgr.remember("회의: 배포 일정 논의", source="session_end", scope=U1_MAIN)

    out = await mgr.observe(
        [UserMessage(content="배포 회의 언제였지", timestamp=0)],
        {"user_id": "u1", "agent_id": "main", "session_id": "s1"},
    )
    headers = [m.content.split("\n")[0] for m in out[:-1]]
    assert headers == ["[핵심 사실]", "[장기 기억]", "[절차 기억]"]
    assert "부산" in out[0].content and "배포 일정" in out[1].content and "/deploy" in out[2].content
    assert (await mgr.get((await mgr.recent(scope=U1_MAIN, limit=10))[0].id)).last_accessed is not None


async def test_consolidate_extracts_shared_facts_once_and_flushes_rehearsal(memory):
    from jarvis.memory.consolidation.semantic_extract import Fact

    calls: list[str] = []

    async def extractor(summary: str) -> list[Fact]:
        calls.append(summary)
        return [Fact("거주지", "부산", 0.9), Fact("기분", "좋음", 0.2)]

    mgr = MemoryManager(memory.store, memory.working, extractor=extractor, importance_threshold=0.5)
    episode = await mgr.remember("세션 요약: 부산으로 이사했다", source="session_end", scope=U1_MAIN)
    state = await mgr.working_state(U1_MAIN)
    state.rehearse(episode)
    await mgr.working.save(state)

    assert await mgr.consolidate(U1_MAIN) == 1  # importance 0.2 는 버린다
    facts = await mgr.recent(scope=U1_RESEARCHER, kinds=[MemoryKind.SEMANTIC])  # shared 라 서브 에이전트도 본다
    assert [f.content for f in facts] == ["거주지: 부산"]
    assert facts[0].source == "extracted" and facts[0].metadata["from_episode"] == episode
    assert (await mgr.get(episode)).rehearsal_count == 1
    assert (await mgr.working_state(U1_MAIN)).rehearsal == {}

    assert await mgr.consolidate(U1_MAIN) == 0  # 두 번째는 아무것도 안 쓴다
    assert calls == ["세션 요약: 부산으로 이사했다"]


async def test_consolidate_without_extractor_only_flushes(memory):
    assert await memory.consolidate(U1_MAIN) == 0
