"""MemoryService: 쓰기 규칙, 범위 해석, 저장소 격리, LongTermMemory 미들웨어를 통한 상속."""

import pytest

from jarvis.memory import WRITE_RULES, MemoryItem, MemoryKind, MemoryScope, MemoryService
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.stores.protocol import ItemStore
from jarvis.model_layer.types import UserMessage

U1_MAIN = MemoryScope(user_id="u1", agent_id="main", session_id="s1")
U1_RESEARCHER = MemoryScope(user_id="u1", agent_id="researcher", session_id="agent_researcher__s1")
U2_MAIN = MemoryScope(user_id="u2", agent_id="main", session_id="t1")


@pytest.fixture
def memory() -> MemoryService:
    return MemoryService(InMemoryItemStore())


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


async def test_unknown_source_is_an_agent_episode_not_a_user_fact(memory):
    """의미 기억은 사용자 프로필이다. 규칙에 없는 경로가 쓴 글이 [핵심 사실] 에 올라가면 안 된다."""
    item_id = await memory.remember("새 경로가 남긴 결과", source="some_new_path", scope=U1_MAIN)
    item = await memory.get(item_id)
    assert item is not None and (item.kind, item.visibility) == (MemoryKind.EPISODIC, "private")
    assert await memory.fixed_facts(U1_MAIN) == []


async def test_user_profile_fact_written_by_one_agent_is_fixed_for_every_agent(memory):
    """사용자 프로필은 에이전트가 아니라 사용자의 것이다. KAREN 이 저장한 사실도 JARVIS 의 [핵심 사실] 에 들어간다."""
    karen = MemoryScope(user_id="u1", agent_id="karen")
    await memory.remember("관심 지역: 서울", source="explicit", scope=karen)
    for reader in (U1_MAIN, karen, U1_RESEARCHER):
        assert [i.content for i in await memory.fixed_facts(reader)] == ["관심 지역: 서울"]
    assert await memory.fixed_facts(U2_MAIN) == []


def test_every_semantic_rule_is_shared():
    """의미 기억을 쓰는 규칙은 전부 shared 다. private 의미 기억은 사용자 프로필인데 일부 에이전트만 보게 된다."""
    assert all(r.visibility == "shared" for r in WRITE_RULES.values() if r.kind is MemoryKind.SEMANTIC)


def test_every_known_source_has_a_rule():
    assert {"explicit", "auto_summary", "manual_compact", "session_end", "thought", "journal", "promoted"} <= set(
        WRITE_RULES
    )


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


# ── observe: harness context 에서 범위를 조립한다 ───────────────────────────


async def test_observe_scopes_by_context(memory):
    await memory.remember("선호 음료: 커피", source="explicit", scope=U1_MAIN)
    await memory.remember("세션 요약: 예산 논의", source="auto_summary", scope=U1_MAIN)
    ltm = MemoryService(memory.store, inject_limit=5)
    msgs = [UserMessage(content="커피 그리고 예산 얘기", timestamp=0)]

    def injected(out: list) -> str:  # 고정 사실 블록 + 회상 블록(원 메시지 앞에 붙는다)
        return "\n".join(m.content for m in out[:-1])

    as_main = await ltm.observe(msgs, {"user_id": "u1", "agent_id": "main", "session_id": "s9"})
    assert "커피" in injected(as_main) and "예산" in injected(as_main)

    as_sub = await ltm.observe(msgs, {"user_id": "u1", "agent_id": "researcher", "session_id": "x"})
    assert "커피" in injected(as_sub) and "예산" not in injected(as_sub)

    as_other = await ltm.observe(msgs, {"user_id": "u2", "agent_id": "main"})
    assert as_other == msgs


async def test_observe_without_user_in_context_falls_back_to_local(memory):
    await memory.remember("로컬 사용자 기억", source="explicit", scope=MemoryScope(user_id="local"))
    out = await memory.observe([UserMessage(content="사용자 기억", timestamp=0)], {"session_id": "s"})
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
    mgr = MemoryService(memory.store, procedures=procedures, fixed_facts=1, inject_limit=3)
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

    mgr = MemoryService(memory.store, memory.working, extractor=extractor, importance_threshold=0.5)
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


# ── 5단계: 간섭 탐지 ─────────────────────────────────────────────────────────


async def test_find_interference_pairs_similar_facts_with_different_keys():
    from jarvis.memory.long_term.semantic import find_interference, similarity

    a = MemoryItem(content="출근 수단: 지하철로 출근", kind=MemoryKind.SEMANTIC, scope=U1_MAIN)
    b = MemoryItem(content="통근 방법: 지하철로 출근", kind=MemoryKind.SEMANTIC, scope=U1_MAIN)
    c = MemoryItem(content="반려견 이름: 보리", kind=MemoryKind.SEMANTIC, scope=U1_MAIN)
    assert similarity(a.content, b.content) >= 0.5
    assert find_interference([a, b, c], threshold=0.5) == [(a.id, b.id)]
    # 같은 주제는 대체 규칙 몫이라 간섭 후보가 아니다
    d = MemoryItem(content="출근 수단: 버스로 출근", kind=MemoryKind.SEMANTIC, scope=U1_MAIN)
    assert find_interference([a, d], threshold=0.1) == []


async def test_consolidate_marks_interference_once(memory):
    from jarvis.memory.long_term.semantic import CONFLICTS_KEY

    mgr = MemoryService(memory.store, memory.working, interference_threshold=0.5)
    a = await mgr.remember("출근 수단: 지하철로 출근", source="explicit", scope=U1_MAIN)
    b = await mgr.remember("통근 방법: 지하철로 출근", source="explicit", scope=U1_MAIN)

    await mgr.consolidate(U1_MAIN)
    await mgr.consolidate(U1_MAIN)  # 두 번 돌려도 목록이 늘지 않는다

    assert (await mgr.get(a)).metadata[CONFLICTS_KEY] == [b]
    assert (await mgr.get(b)).metadata[CONFLICTS_KEY] == [a]
    # 여전히 둘 다 검색된다. 표시만 하고 대체하지 않는다
    assert len(await mgr.recall("지하철 출근", scope=U1_MAIN)) == 2


# ── 5단계: 의미 유사도 검색 ──────────────────────────────────────────────────


async def test_remember_embeds_and_recall_finds_paraphrase():
    from jarvis.memory.eval.fake_embedder import FakeEmbedder

    mgr = MemoryService(InMemoryItemStore(), embedder=FakeEmbedder())
    item_id = await mgr.remember("거주지: 부산", source="explicit", scope=U1_MAIN)
    item = await mgr.get(item_id)
    assert item.embedding is not None and item.embedding_model == "fake-bow-64"

    # 키워드로는 못 잡는 의역을 벡터로 잡는다
    assert [i.content for i in await mgr.recall("사는 곳", scope=U1_MAIN)] == ["거주지: 부산"]
    assert await mgr.recall("자동차 번호", scope=U1_MAIN) == []


async def test_embedding_failure_does_not_block_remember():
    class Broken:
        model, dimensions = "broken", 2

        async def embed(self, texts):
            raise RuntimeError("down")

    mgr = MemoryService(InMemoryItemStore(), embedder=Broken())
    item_id = await mgr.remember("거주지: 부산", source="explicit", scope=U1_MAIN)
    assert (await mgr.get(item_id)).embedding is None
    assert [i.content for i in await mgr.recall("거주지", scope=U1_MAIN)] == ["거주지: 부산"]  # 키워드로는 찾힌다


async def test_reembed_only_touches_stale_items():
    from jarvis.memory.eval.fake_embedder import FakeEmbedder

    store = InMemoryItemStore()
    plain = MemoryService(store)
    await plain.remember("거주지: 부산", source="explicit", scope=U1_MAIN)
    await plain.remember("직장: 알파", source="explicit", scope=U1_MAIN)

    mgr = MemoryService(store, embedder=FakeEmbedder())
    assert await mgr.reembed(U1_MAIN) == 2
    assert await mgr.reembed(U1_MAIN) == 0  # 두 번째는 할 일이 없다
    assert [i.content for i in await mgr.recall("사는 곳", scope=U1_MAIN)] == ["거주지: 부산"]
