"""memory 기능의 MemoryService: 쓰기 규칙, 범위 격리, 턴 전 주입과 되뇌기, 턴 일화, 공고화, 임베딩, 작업 패턴."""

import pytest
from datetime import datetime, timedelta

from jarvis.memory.memory_service import LTM_HEADER, PROCEDURES_HEADER, TURN_SOURCE, TURN_STEPS
from jarvis.memory.long_term.task_pattern import PATTERN_HEADER, SAVE_HINT_HEADER, TaskPattern
from jarvis.model_layer.model_types import AssistantMessage, TextContent, UserMessage
from tests.fixtures.procedures_helpers import EDM_SCOPE, edm_learner, record_turn
from jarvis.memory import WRITE_RULES, MemoryKind, MemoryScope, MemoryService
from jarvis.memory.long_term.procedural import InMemoryProcedures, Procedure
from jarvis.memory.consolidation.semantic_extract import Fact
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.long_term.semantic import CONFLICTS_KEY
from jarvis.memory.eval.fake_embedder import FakeEmbedder


U1_MAIN = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


U1_RESEARCHER = MemoryScope(user_id="u1", agent_id="researcher", session_id="agent_researcher__s1")


U2_MAIN = MemoryScope(user_id="u2", agent_id="main", session_id="t1")


CTX = {"session_id": "s1", "user_id": "u1", "agent_id": "main"}


SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


NOW = datetime(2026, 10, 18, 12, 0)


def _u(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


def _a(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)], timestamp=0)


async def _turns(memory: MemoryService, pairs: list[tuple[str, str]], ctx: dict = CTX) -> list:
    history: list = []
    out: list = []
    for user, answer in pairs:
        history.append(_u(user))
        out = await memory.observe(history, ctx)
        await memory.reinforce(answer, ctx)
        history.append(_a(answer))
    return out


async def _ltm_block(memory: MemoryService, history: list) -> str:
    blocks = await memory.observe(history, CTX)
    return next((m.content for m in blocks if isinstance(m.content, str) and m.content.startswith(LTM_HEADER)), "")


@pytest.fixture
def memory() -> MemoryService:
    return MemoryService(InMemoryItemStore())


async def test_remember_applies_write_rule_for_source(memory):
    item_id = await memory.remember("거주지: 서울", source="explicit", scope=U1_MAIN)
    item = await memory.get(item_id)
    assert item is not None
    assert (item.kind, item.author) == (MemoryKind.SEMANTIC, "user")

    summary_id = await memory.remember("요약", source="manual_compact", scope=U1_RESEARCHER)
    summary = await memory.get(summary_id)
    assert summary is not None
    assert (summary.kind, summary.author) == (MemoryKind.EPISODIC, "researcher")
    assert summary.session_id == "agent_researcher__s1"


async def test_remember_keyword_overrides_rule(memory):
    item_id = await memory.remember("x", source="explicit", scope=U1_MAIN, kind=MemoryKind.EPISODIC, tags=["t"])
    item = await memory.get(item_id)
    assert item is not None and item.kind is MemoryKind.EPISODIC and item.tags == ["t"]


async def test_unknown_source_is_an_agent_episode_not_a_user_fact(memory):
    """의미 기억은 사용자 프로필이다. 규칙에 없는 경로가 쓴 글이 [핵심 사실] 에 올라가면 안 된다."""
    item_id = await memory.remember("새 경로가 남긴 결과", source="some_new_path", scope=U1_MAIN)
    item = await memory.get(item_id)
    assert item is not None and item.kind is MemoryKind.EPISODIC
    assert await memory.fixed_facts(U1_MAIN) == []


async def test_user_profile_fact_written_by_one_agent_is_fixed_for_every_agent(memory):
    """사용자 프로필은 에이전트가 아니라 사용자의 것이다. KAREN 이 저장한 사실도 JARVIS 의 [핵심 사실] 에 들어간다."""
    karen = MemoryScope(user_id="u1", agent_id="karen")
    await memory.remember("관심 지역: 서울", source="explicit", scope=karen)
    for reader in (U1_MAIN, karen, U1_RESEARCHER):
        assert [i.content for i in await memory.fixed_facts(reader)] == ["관심 지역: 서울"]
    assert await memory.fixed_facts(U2_MAIN) == []


def test_every_known_source_has_a_rule():
    assert {"explicit", "turn", "manual_compact", "thought", "journal", "promoted", "task_pattern"} <= set(WRITE_RULES)


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


async def test_same_topic_fact_supersedes_older_one_on_write(memory):
    old = await memory.remember("거주지: 서울", source="explicit", scope=U1_MAIN)
    new = await memory.remember("거주지: 부산", source="explicit", scope=U1_MAIN)
    assert [i.content for i in await memory.recall("거주지", scope=U1_MAIN)] == ["거주지: 부산"]
    assert (await memory.get(old)).superseded_by == new
    assert "key:거주지" in (await memory.get(new)).tags


async def test_late_dated_fact_is_superseded_by_existing_newer_one(memory):
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


async def test_consolidate_marks_interference_once(memory):
    mgr = MemoryService(memory.store, memory.working, interference_threshold=0.5)
    a = await mgr.remember("출근 수단: 지하철로 출근", source="explicit", scope=U1_MAIN)
    b = await mgr.remember("통근 방법: 지하철로 출근", source="explicit", scope=U1_MAIN)

    await mgr.consolidate(U1_MAIN)
    await mgr.consolidate(U1_MAIN)  # 두 번 돌려도 목록이 늘지 않는다

    assert (await mgr.get(a)).metadata[CONFLICTS_KEY] == [b]
    assert (await mgr.get(b)).metadata[CONFLICTS_KEY] == [a]
    # 여전히 둘 다 검색된다. 표시만 하고 대체하지 않는다
    assert len(await mgr.recall("지하철 출근", scope=U1_MAIN)) == 2


async def test_remember_embeds_and_recall_finds_paraphrase():
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
    store = InMemoryItemStore()
    plain = MemoryService(store)
    await plain.remember("거주지: 부산", source="explicit", scope=U1_MAIN)
    await plain.remember("직장: 알파", source="explicit", scope=U1_MAIN)

    mgr = MemoryService(store, embedder=FakeEmbedder())
    assert await mgr.reembed(U1_MAIN) == 2
    assert await mgr.reembed(U1_MAIN) == 0  # 두 번째는 할 일이 없다
    assert [i.content for i in await mgr.recall("사는 곳", scope=U1_MAIN)] == ["거주지: 부산"]


async def test_legacy_stm_on_in_memory_store_is_none():
    memory = MemoryService(InMemoryItemStore())

    assert await memory.legacy_stm_rows() is None
    await memory.drop_legacy_stm()


async def test_procedures_block_drops_colon_tail_only_without_description():
    procedures = [Procedure(name="deploy", description="다음 순서:"), Procedure(name="bare", description="")]
    memory = MemoryService(InMemoryItemStore(), procedures=InMemoryProcedures(procedures))

    out = await memory.observe([_u("deploy bare")], CTX)

    assert out[0].content == f"{PROCEDURES_HEADER}\n- /deploy: 다음 순서:\n- /bare"


async def test_recall_block_is_injected_and_only_used_recall_is_rehearsed():
    memory = MemoryService(InMemoryItemStore())
    item_id = await memory.remember("선호 음료: 커피", source="explicit", scope=SCOPE)

    out = await memory.observe([_u("선호 음료 뭐였지")], CTX)

    # 의미 사실은 고정 블록으로 항상 들어가고, 회상 블록은 거기 없는 것만 싣는다
    assert out[0].content.startswith("[핵심 사실]") and "커피" in out[0].content
    assert not any(m.content.startswith("[장기 기억]") for m in out)
    # 떠올렸다고 바로 세지 않는다. 답에 쓰였을 때만, 한 턴에 한 번 센다
    assert (await memory.working_state(SCOPE)).rehearsal == {}
    assert await memory.reinforce("선호 음료는 커피였어요", CTX) == [item_id]
    assert await memory.reinforce("선호 음료는 커피였어요", CTX) == []
    assert (await memory.working_state(SCOPE)).rehearsal == {item_id: 1}
    await memory.observe([_u("선호 음료 뭐였지"), _a("커피"), _u("선호 음료 다시")], CTX)
    assert await memory.reinforce("오늘은 비가 와요", CTX) == []
    assert (await memory.working_state(SCOPE)).rehearsal == {item_id: 1}


async def test_notes_are_session_scoped():
    memory = MemoryService(InMemoryItemStore())

    await memory.add_note("메모 1", scope=SCOPE)
    await memory.add_note("메모 2", scope=SCOPE)

    assert (await memory.working_state(SCOPE)).notes == ["메모 1", "메모 2"]
    assert (await memory.working_state(SCOPE.with_session("s2"))).notes == []


async def test_observe_and_recall_messages_scope_by_turn_context():
    memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
    await memory.remember("프로젝트 마감: 금요일", source="explicit", scope=SCOPE)

    out = await memory.observe([_u("프로젝트 마감 언제")], CTX)
    recalled = await memory.recall_messages("프로젝트 마감", CTX, limit=5)

    assert out[0].content.startswith("[장기 기억]") and "금요일" in out[0].content
    assert [m.content for m in recalled] == ["프로젝트 마감: 금요일"]


@pytest.mark.parametrize("ctx", [{"session_id": "s1"}, {}])
async def test_observe_without_user_in_context_uses_local_scope(ctx):
    memory = MemoryService(InMemoryItemStore())
    await memory.remember("로컬 기억", source="explicit", scope=MemoryScope(user_id="local"))

    out = await memory.observe([_u("로컬 기억 찾기")], ctx)

    assert "로컬 기억" in out[0].content


async def test_keeps_three_turns_and_records_each_turn_once():
    store = InMemoryItemStore()
    memory = MemoryService(store, stm_turns=3)

    out = await _turns(memory, [(f"질문 {i}", f"답 {i}") for i in range(5)])

    window = [m.content for m in out if m.role == "user" and not m.content.startswith("[")]
    assert window == ["질문 2", "질문 3", "질문 4"]
    turns = [i for i in await store.recent(SCOPE, limit=50) if i.source == TURN_SOURCE]
    assert sorted(i.metadata["turn"] for i in turns) == [1, 2, 3, 4, 5]
    assert "사용자: 질문 0\n답: 답 0" in {i.content for i in turns}
    assert all(i.kind is MemoryKind.EPISODIC and i.scope.agent_id == "main" for i in turns)
    # 같은 턴을 다시 돌려도(재시도) 같은 항목을 덮는다
    history = [m for p in [(f"질문 {i}", f"답 {i}") for i in range(4)] for m in (_u(p[0]), _a(p[1]))] + [_u("질문 4")]
    await memory.observe(history, CTX)
    await memory.reinforce("답 4", CTX)
    assert len([i for i in await store.recent(SCOPE, limit=50) if i.source == TURN_SOURCE]) == 5


async def test_turn_past_the_window_comes_back_through_recall_but_window_turns_do_not_repeat():
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    pairs = [
        ("내 차 번호는 12가3456이야", "알겠습니다"), ("날씨 어때", "맑음"), ("점심 추천", "국수"), ("저녁 추천", "밥"),
    ]
    await _turns(memory, pairs)

    assert await _turns(memory, []) == []
    history = [m for u, a in pairs for m in (_u(u), _a(a))] + [_u("내 차 번호 뭐였지?")]
    assert "12가3456" in await _ltm_block(memory, history)
    history = [m for u, a in pairs[:2] for m in (_u(u), _a(a))] + [_u("내 차 번호 뭐였지?")]
    assert await _ltm_block(memory, history) == ""


async def test_consolidate_extracts_once_per_session_from_user_turns():
    calls: list[str] = []

    async def extractor(text: str) -> list[Fact]:
        calls.append(text)
        return [Fact(key="차 번호", value="12가3456", importance=0.9)]

    memory = MemoryService(InMemoryItemStore(), extractor=extractor, stm_turns=3)
    await _turns(memory, [("내 차 번호는 12가3456이야", "알겠습니다"), ("날씨 어때", "맑음")])
    await _turns(memory, [("다른 세션", "응")], {**CTX, "session_id": "s2"})

    assert await memory.consolidate(SCOPE) == 2
    first = next(c for c in calls if "12가3456" in c)
    assert len(calls) == 2 and first.index("12가3456") < first.index("날씨")
    # 답("맑음")의 추천이 사용자 사실로 뽑히지 않게 사용자 발화만 넘긴다
    assert "맑음" not in first and "알겠습니다" not in first
    assert await memory.consolidate(SCOPE) == 0 and len(calls) == 2


async def test_thought_logs_do_not_take_recall_slots_from_turns():
    """실서버에서 본 실패: 사고 로그가 사용자 말을 다시 적어 같은 낱말로 더 최근에 걸리고, 턴 일화는 밀려났다."""
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    pairs = [
        ("내 자전거 자물쇠 비밀번호는 4719야", "알겠습니다"),
        ("저녁 추천", "국수"), ("음악 추천", "재즈"), ("차 추천", "홍차"),
    ]
    await _turns(memory, pairs)
    for i in range(5):
        thought = f'{{"observation": "사용자가 자전거 자물쇠 비밀번호 얘기 {i}"}}'
        await memory.remember(thought, source="thought", scope=SCOPE)
    history = [m for u, a in pairs for m in (_u(u), _a(a))] + [_u("내 자전거 자물쇠 비밀번호가 뭐였지?")]

    block = await _ltm_block(memory, history)

    assert "4719" in block and "observation" not in block


async def test_window_turns_do_not_shrink_recall_slots():
    memory = MemoryService(InMemoryItemStore(), stm_turns=3, inject_limit=1, fixed_facts=0)
    # 창 안의 두 턴이 같은 낱말로 더 최근에 걸린다. 그 둘을 한도 안에서 빼면 회상 자리가 남지 않았다
    pairs = [("자전거 비밀번호는 4719", "네"), ("자전거 비밀번호 얘기 하나", "네"), ("자전거 비밀번호 얘기 둘", "네")]
    await _turns(memory, pairs)
    history = [m for u, a in pairs for m in (_u(u), _a(a))] + [_u("자전거 비밀번호?")]

    assert "4719" in await _ltm_block(memory, history)


async def test_turn_episode_keeps_first_tool_as_task_type_and_outcome():
    store = InMemoryItemStore()
    memory = MemoryService(store, stm_turns=3)

    await memory.observe([_u("공고 보고 대출 계산해줘")], CTX)
    await memory.reinforce("PDF 를 못 읽었습니다", CTX, tools=["lh_notice", "housing_loan", "lh_notice"], failed=True)
    await memory.observe([_u("공고 보고 대출 계산해줘"), _a("PDF 를 못 읽었습니다"), _u("안녕")], CTX)
    await memory.reinforce("안녕하세요", CTX)

    meta = {i.metadata["turn"]: i.metadata for i in await store.recent(SCOPE, limit=10)}
    assert meta[1]["task_type"] == "lh_notice" and meta[1]["outcome"] == "failure"
    assert meta[1]["tools"] == ["lh_notice", "housing_loan"]
    assert meta[2]["task_type"] == "chat" and meta[2]["outcome"] == "success"


async def test_turn_steps_keep_short_args_only():
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)

    await record_turn(memory, 0, steps=[("write_file", {"path": "a", "content": "x" * 5000})])

    item = (await memory.store.recent(EDM_SCOPE, limit=1))[0]
    [step] = item.metadata[TURN_STEPS]
    assert step["name"] == "write_file" and len(step["args"]["content"]) == 200


async def test_forget_session_removes_only_that_sessions_memory():
    """세션 삭제: 그 세션의 턴 일화, 사고 로그, 작업 기억만. 이름이 겹치는 세션과 사용자 프로필은 남는다."""
    memory = MemoryService(InMemoryItemStore())
    await _turns(memory, [("자전거 비밀번호는 4719", "네")])
    await memory.remember("사고: 비밀번호", source="thought", scope=SCOPE)
    await memory.add_note("메모", scope=SCOPE)
    await _turns(memory, [("다른 세션", "네")], {**CTX, "session_id": "s10"})
    await memory.remember("거주지: 부산", source="explicit", scope=SCOPE.with_session(None))

    assert await memory.forget_session("s1") == (2, 1)
    assert await memory.forget_session("s1") == (0, 0)
    left = {i.content for i in await memory.store.recent(SCOPE, limit=20)}
    assert left == {"사용자: 다른 세션\n답: 네", "거주지: 부산"}
    assert (await memory.working_state(SCOPE)).notes == []


async def test_deictic_turn_recalls_memory_about_previous_topic():
    memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
    await memory.remember("배포: 스테이징은 금요일에 막아 둔다", source="session_end", scope=SCOPE)

    out = await memory.observe([_u("배포 일정 정리해줘"), _a("정리했다"), _u("그거 다시 해줘")], CTX)

    assert any("금요일" in m.content for m in out if isinstance(m.content, str))


async def test_fixed_facts_keep_old_important_fact_past_candidate_pool():
    memory = MemoryService(InMemoryItemStore(), fixed_facts=3)
    await memory.remember("이름: 재훈", source="explicit", scope=SCOPE, created_at=NOW - timedelta(days=100))
    for i in range(12):
        await memory.remember(f"취향{i}: 사소함", source="extracted", scope=SCOPE, importance=0.3,
                              created_at=NOW - timedelta(hours=i))

    assert any("재훈" in i.content for i in await memory.fixed_facts(SCOPE))


async def test_fixed_facts_are_not_rehearsed_unless_the_query_hits_them():
    memory = MemoryService(InMemoryItemStore())
    item_id = await memory.remember("선호 음료: 커피", source="explicit", scope=SCOPE)

    for _ in range(3):
        await memory.observe([_u("오늘 일정 알려줘")], CTX)

    assert (await memory.working_state(SCOPE)).rehearsal == {}
    assert (await memory.get(item_id)).last_accessed is None


async def test_referent_is_stored_searched_and_shown():
    memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
    await memory.remember("그 방법 앞으로 계속 써", source="explicit", scope=SCOPE,
                          referent="배포 스크립트 고쳐줘\n롤백 방식으로 고쳤다")

    hits = await memory.recall("롤백", SCOPE)
    out = await memory.observe([_u("롤백 어떻게 하기로 했지")], CTX)

    assert [h.content for h in hits] == ["그 방법 앞으로 계속 써"]
    block = next(m.content for m in out if isinstance(m.content, str) and m.content.startswith("[장기 기억]"))
    assert "(가리킨 대화: 배포 스크립트 고쳐줘 / 롤백 방식으로 고쳤다)" in block


async def test_consolidate_runs_attached_refiner_once(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    learner, store, distiller = edm_learner(tmp_path, memory)
    memory.attach_refiner(learner.refine)
    for i in range(3):
        await record_turn(memory, i)

    await memory.consolidate(EDM_SCOPE)
    await memory.consolidate(EDM_SCOPE)

    assert len(store.list()) == 1 and distiller.calls == 1


KAREN = MemoryScope(user_id="u1", agent_id="karen", session_id="k1")


KAREN_LATER = MemoryScope(user_id="u1", agent_id="karen", session_id="k2")


MAIN = MemoryScope(user_id="u1", agent_id="main", session_id="m1")


BUDGET = TaskPattern(
    "예산 기반 공고 추천",
    "총예산과 현금으로 공고를 추천해 달라는 요청",
    "대출 = 총예산 이내 금액 - 현금. 금리는 연 4% 가정. housing_budget 으로 한 번에 찾는다",
    ("예산", "현금", "월 상환", "추천"),
)


async def observe(memory: MemoryService, scope: MemoryScope, text: str) -> list[str]:
    context = {"user_id": scope.user_id, "agent_id": scope.agent_id, "session_id": scope.session_id}
    out = await memory.observe([UserMessage(content=text, timestamp=0)], context)
    return [m.content for m in out[:-1]]


async def test_remember_pattern_saves_agent_private_procedural(memory):
    item_id = await memory.remember_pattern(BUDGET, KAREN)
    item = await memory.get(item_id)
    assert (item.kind, item.author) == (MemoryKind.PROCEDURAL, "user")
    assert item.scope.agent_id == "karen" and item.scope.session_id is None


async def test_remember_pattern_twice_keeps_one_and_updates(memory):
    await memory.remember_pattern(BUDGET, KAREN)
    changed = TaskPattern(BUDGET.name, BUDGET.when, "금리는 연 3.5% 가정", BUDGET.keywords)
    await memory.remember_pattern(changed, KAREN_LATER)
    patterns = await memory.task_patterns(KAREN)
    assert [p.steps for p in patterns] == ["금리는 연 3.5% 가정"]


async def test_observe_other_agent_does_not_see_or_recall_it(memory):
    await memory.remember_pattern(BUDGET, KAREN)
    assert await memory.task_patterns(MAIN) == []
    blocks = await observe(memory, MAIN, "예산 3억 현금 1억으로 공고 추천해줘")
    assert not any(b.startswith(PATTERN_HEADER) for b in blocks)


async def test_observe_same_agent_recalls_in_a_new_session(memory):
    await memory.remember_pattern(BUDGET, KAREN)
    blocks = await observe(memory, KAREN_LATER, "예산 3억 현금 1억으로 공고 추천해줘")
    pattern = next(b for b in blocks if b.startswith(PATTERN_HEADER))
    assert "대출 = 총예산 이내 금액 - 현금" in pattern
    # 일반 회상 블록에 같은 내용이 또 들어가지 않는다
    assert not any(b.startswith("[장기 기억]") and "예산 기반 공고 추천" in b for b in blocks)


async def test_observe_unrelated_request_gets_no_pattern(memory):
    await memory.remember_pattern(BUDGET, KAREN)
    assert not any(b.startswith(PATTERN_HEADER) for b in await observe(memory, KAREN_LATER, "SH 공고 보여줘"))


async def test_observe_teaching_message_gets_a_save_hint(memory):
    blocks = await observe(memory, KAREN, "앞으로 비슷한 요청이 오면 이렇게 계산해. 기억해")
    assert any(b.startswith(SAVE_HINT_HEADER) and "remember_task_pattern" in b for b in blocks)


async def test_forget_pattern_removes_once(memory):
    await memory.remember_pattern(BUDGET, KAREN)
    assert await memory.forget_pattern(BUDGET.name, KAREN_LATER)
    assert await memory.task_patterns(KAREN) == []
    assert not await memory.forget_pattern(BUDGET.name, KAREN)
