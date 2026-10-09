"""MemoryManager: 쓰기 규칙, 범위 해석, 저장소 격리, LongTermMemory 미들웨어를 통한 상속."""

import pytest

from jarvis.agent_layer.memory.long_term import LongTermMemory
from jarvis.memory import WRITE_RULES, MemoryKind, MemoryManager, MemoryScope, current_scope
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
    ltm = LongTermMemory(memory, inject_limit=5)
    msgs = [UserMessage(content="커피 그리고 예산 얘기", timestamp=0)]

    as_main = await ltm.transform(msgs, {"user_id": "u1", "agent_id": "main", "session_id": "s9"})
    assert "커피" in as_main[0].content and "예산" in as_main[0].content

    as_sub = await ltm.transform(msgs, {"user_id": "u1", "agent_id": "researcher", "session_id": "x"})
    assert "커피" in as_sub[0].content and "예산" not in as_sub[0].content

    as_other = await ltm.transform(msgs, {"user_id": "u2", "agent_id": "main"})
    assert as_other == msgs


async def test_middleware_without_user_in_context_falls_back_to_local(memory):
    await memory.remember("로컬 사용자 기억", source="explicit", scope=MemoryScope(user_id="local"))
    ltm = LongTermMemory(memory)
    out = await ltm.transform([UserMessage(content="사용자 기억", timestamp=0)], {"session_id": "s"})
    assert "로컬 사용자 기억" in out[0].content
