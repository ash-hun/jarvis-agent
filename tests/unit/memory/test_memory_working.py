"""작업 기억: 창과 턴 창, 컴팩션 persist(재요약 없음), 턴 기록, 되뇌기, 메모, 미들웨어 어댑터."""

import pytest

from jarvis.memory.working import InMemoryWorkingStore, WorkingState, WorkingStore, apply_window, cut_at_user_boundary
from jarvis.model_layer.types import AssistantMessage, TextContent, ToolResultMessage, UserMessage
from jarvis.memory.working.window import SUMMARY_HEADER, last_turns
from jarvis.memory.memory_service import LTM_HEADER, TURN_SOURCE
from jarvis.memory.consolidation.semantic_extract import Fact
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.consolidation import llm_summarizer
from jarvis.memory import MemoryScope, MemoryService
from jarvis.memory.eval.probe import count_llm_calls
from jarvis.memory.types import MemoryKind

CTX = {"session_id": "s1", "user_id": "u1", "agent_id": "main"}
SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


def _u(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


def _a(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)], timestamp=0)


def _t(text: str) -> ToolResultMessage:
    return ToolResultMessage(tool_call_id="c", tool_name="bash", content=[TextContent(text=text)])


# ── 창 ───────────────────────────────────────────────────────────────────────


def test_cut_at_user_boundary_drops_orphaned_tool_results():
    msgs = [_t("orphan"), _a("a"), _u("q"), _a("r")]
    assert cut_at_user_boundary(msgs) == msgs[2:]
    assert cut_at_user_boundary([_a("only")]) == [_a("only")]


def test_apply_window_keeps_tail_and_starts_at_user():
    msgs = [_u("1"), _a("2"), _u("3"), _a("4"), _u("5"), _a("6")]
    out = apply_window(msgs, 3)
    assert [m.role for m in out] == ["user", "assistant"]  # [a4, u5, a6] 에서 고아 a4 제거
    assert apply_window(msgs, 0) == msgs
    assert apply_window(msgs, 10) == msgs


# ── 작업 기억 저장소 ─────────────────────────────────────────────────────────


async def test_in_memory_working_store_roundtrip_and_isolation():
    store = InMemoryWorkingStore()
    assert isinstance(store, WorkingStore)
    empty = await store.load(SCOPE)
    assert empty.summary is None and empty.summary_covers == 0

    state = WorkingState(scope=SCOPE, summary="요약", summary_covers=4)
    state.add_note("n1")
    assert state.rehearse("item") == 1 and state.rehearse("item") == 2
    await store.save(state)

    loaded = await store.load(SCOPE)
    assert (loaded.summary, loaded.summary_covers, loaded.notes, loaded.rehearsal) == ("요약", 4, ["n1"], {"item": 2})
    # 사본이라 load 결과를 고쳐도 저장소는 그대로
    loaded.notes.append("x")
    assert (await store.load(SCOPE)).notes == ["n1"]
    # 다른 세션은 빈 상태
    assert (await store.load(SCOPE.with_session("s2"))).summary is None
    await store.clear(SCOPE)
    assert (await store.load(SCOPE)).summary is None


# ── observe: 컴팩션은 한 번, 요약은 persist ──────────────────────────────────


def _manager(model, **kw) -> MemoryService:
    return MemoryService(
        InMemoryItemStore(), InMemoryWorkingStore(), summarizer=llm_summarizer(model), **kw
    )


def _history(n: int, chars: int = 100) -> list:
    return [_u(f"m{i} " + "x" * chars) if i % 2 == 0 else _a(f"m{i} " + "x" * chars) for i in range(n)]


async def test_over_threshold_summarizes_once_and_not_again_next_turn(faux_model_with_response):
    model = faux_model_with_response("압축 요약")
    memory = _manager(model, threshold_chars=1500, keep_recent=2)
    history = _history(10)

    with count_llm_calls("faux") as c:
        first = await memory.observe(history, CTX)
    assert c.calls == 1
    assert first[0].content.startswith(SUMMARY_HEADER) and "압축 요약" in first[0].content
    assert len(first) == 1 + 2

    state = await memory.working_state(SCOPE)
    assert state.summary == "압축 요약" and state.summary_covers == 8

    history = history + _history(2)[:2]  # 다음 턴: 메시지 2개 추가
    with count_llm_calls("faux") as c:
        second = await memory.observe(history, CTX)
    assert c.calls == 0  # 요약이 저장돼 있어 재요약하지 않는다
    assert second[0].content.startswith(SUMMARY_HEADER)
    assert len(second) == 1 + 4  # 요약 + 덮이지 않은 꼬리 4개


async def test_summary_is_written_to_long_term_as_private_episode(faux_model_with_response):
    model = faux_model_with_response("요약본")
    memory = _manager(model, threshold_chars=10, keep_recent=1)
    await memory.observe([_u("a"), _a("b"), _u("c")], CTX)

    items = await memory.recent(scope=SCOPE)
    assert len(items) == 1
    assert (items[0].source, items[0].visibility, items[0].kind.value) == ("auto_summary", "private", "episodic")
    assert items[0].session_id == "s1"


async def test_below_threshold_passes_through_without_llm(faux_model_with_response):
    model = faux_model_with_response("불려선 안 됨")
    memory = _manager(model, threshold_chars=1_000_000)
    msgs = [_u("짧은 메시지")]
    with count_llm_calls("faux") as c:
        assert await memory.observe(msgs, CTX) == msgs
    assert c.calls == 0 and await memory.recent(scope=SCOPE) == []


async def test_summary_failure_keeps_history_and_writes_nothing():
    from jarvis.model_layer.registry import get_default_registry
    from tests.fixtures.faux_provider import FauxProviderFactory
    from jarvis.model_layer.types import ModelConfig

    get_default_registry()._providers["faux"] = FauxProviderFactory.error()
    memory = _manager(ModelConfig(provider="faux", model="faux-model"), threshold_chars=10, keep_recent=1)
    msgs = [_u("a"), _a("b"), _u("c")]

    assert await memory.observe(msgs, CTX) == msgs
    assert await memory.recent(scope=SCOPE) == []
    assert (await memory.working_state(SCOPE)).summary is None


async def test_shrunken_history_resets_stale_summary(faux_model_with_response):
    model = faux_model_with_response("요약")
    memory = _manager(model, threshold_chars=10, keep_recent=1)
    await memory.observe(_history(6), CTX)
    assert (await memory.working_state(SCOPE)).summary_covers == 5

    out = await memory.observe([_u("새 세션처럼 짧아짐")], CTX)
    assert out == [_u("새 세션처럼 짧아짐")]


async def test_no_summarizer_means_window_only():
    memory = MemoryService(InMemoryItemStore(), window_size=3)
    out = await memory.observe(_history(10, chars=5), CTX)
    assert len(out) <= 3 and out[0].role == "user"


# ── 회상 주입과 되뇌기 ───────────────────────────────────────────────────────


async def test_recall_block_is_injected_and_only_used_recall_is_rehearsed():
    memory = MemoryService(InMemoryItemStore())
    item_id = await memory.remember("선호 음료: 커피", source="explicit", scope=SCOPE)

    out = await memory.observe([_u("선호 음료 뭐였지")], CTX)
    # 의미 사실은 고정 블록으로 항상 들어가고, 회상 블록은 거기 없는 것만 싣는다
    assert out[0].content.startswith("[핵심 사실]") and "커피" in out[0].content
    assert not any(m.content.startswith("[장기 기억]") for m in out)
    # 떠올렸다고 바로 세지 않는다. 답에 쓰였을 때만 센다
    assert (await memory.working_state(SCOPE)).rehearsal == {}
    assert await memory.reinforce("선호 음료는 커피였어요", CTX) == [item_id]
    assert await memory.reinforce("선호 음료는 커피였어요", CTX) == []  # 같은 턴을 두 번 세지 않는다
    assert (await memory.working_state(SCOPE)).rehearsal == {item_id: 1}

    await memory.observe([_u("선호 음료 뭐였지"), _a("커피"), _u("선호 음료 다시")], CTX)
    assert await memory.reinforce("오늘은 비가 와요", CTX) == []  # 답에 안 쓰였다
    assert (await memory.working_state(SCOPE)).rehearsal == {item_id: 1}


async def test_notes_are_session_scoped():
    memory = MemoryService(InMemoryItemStore())
    await memory.add_note("메모 1", scope=SCOPE)
    await memory.add_note("메모 2", scope=SCOPE)
    assert (await memory.working_state(SCOPE)).notes == ["메모 1", "메모 2"]
    assert (await memory.working_state(SCOPE.with_session("s2"))).notes == []


# ── 턴 컨텍스트로 범위를 정하는 진입점 ──────────────────────────────────────


async def test_observe_and_recall_messages_scope_by_turn_context():
    memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
    await memory.remember("프로젝트 마감: 금요일", source="explicit", scope=SCOPE)

    out = await memory.observe([_u("프로젝트 마감 언제")], CTX)
    assert out[0].content.startswith("[장기 기억]") and "금요일" in out[0].content

    recalled = await memory.recall_messages("프로젝트 마감", CTX, limit=5)
    assert [m.content for m in recalled] == ["프로젝트 마감: 금요일"]


@pytest.mark.parametrize("ctx", [{"session_id": "s1"}, {}])
async def test_observe_without_user_in_context_uses_local_scope(ctx):
    memory = MemoryService(InMemoryItemStore())
    await memory.remember("로컬 기억", source="explicit", scope=MemoryScope(user_id="local"))
    out = await memory.observe([_u("로컬 기억 찾기")], ctx)
    assert "로컬 기억" in out[0].content


# ── STM 턴 창과 턴 기록(EDM) ──────────────────────────────────────────────────


def test_last_turns_keeps_whole_turns_with_tool_pairs():
    msgs = [_u("1"), _a("r1"), _u("2"), _a("call"), _t("out"), _a("r2"), _u("3"), _a("r3"), _u("4")]
    assert last_turns(msgs, 3) == msgs[2:]
    assert last_turns(msgs, 10) == msgs
    assert last_turns([_t("orphan"), _u("1")], 3) == [_u("1")]


async def _turns(memory: MemoryService, pairs: list[tuple[str, str]], ctx: dict = CTX) -> list:
    history: list = []
    out: list = []
    for user, answer in pairs:
        history.append(_u(user))
        out = await memory.observe(history, ctx)
        await memory.reinforce(answer, ctx)
        history.append(_a(answer))
    return out


async def test_turn_mode_keeps_three_turns_and_records_each_turn_once():
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
    assert not memory.summarizes_sessions and MemoryService(store).summarizes_sessions


async def test_turn_past_the_window_comes_back_through_recall_but_window_turns_do_not_repeat():
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    pairs = [
        ("내 차 번호는 12가3456이야", "알겠습니다"), ("날씨 어때", "맑음"), ("점심 추천", "국수"), ("저녁 추천", "밥"),
    ]
    await _turns(memory, pairs)
    out = await _turns(memory, [])  # 빈 호출은 아무것도 하지 않는다
    assert out == []
    history = [m for u, a in pairs for m in (_u(u), _a(a))] + [_u("내 차 번호 뭐였지?")]
    blocks = await memory.observe(history, CTX)
    recall = [m.content for m in blocks if isinstance(m.content, str) and m.content.startswith(LTM_HEADER)]
    assert recall and "12가3456" in recall[0]

    history = [m for u, a in pairs[:2] for m in (_u(u), _a(a))] + [_u("내 차 번호 뭐였지?")]
    blocks = await memory.observe(history, CTX)
    assert not any(isinstance(m.content, str) and m.content.startswith(LTM_HEADER) for m in blocks)


async def test_consolidate_extracts_once_per_session_from_turns():
    calls: list[str] = []

    async def extractor(text: str) -> list[Fact]:
        calls.append(text)
        return [Fact(key="차 번호", value="12가3456", importance=0.9)]

    store = InMemoryItemStore()
    memory = MemoryService(store, extractor=extractor, stm_turns=3)
    await _turns(memory, [("내 차 번호는 12가3456이야", "알겠습니다"), ("날씨 어때", "맑음")])
    await _turns(memory, [("다른 세션", "응")], {**CTX, "session_id": "s2"})
    assert await memory.consolidate(SCOPE) == 2
    first = next(c for c in calls if "12가3456" in c)
    assert len(calls) == 2 and first.index("12가3456") < first.index("날씨")
    # 답("맑음")의 추천이 사용자 사실로 뽑히지 않게 사용자 발화만 넘긴다
    assert "맑음" not in first and "알겠습니다" not in first
    assert await memory.consolidate(SCOPE) == 0 and len(calls) == 2


async def _ltm_block(memory: MemoryService, history: list) -> str:
    blocks = await memory.observe(history, CTX)
    return next((m.content for m in blocks if isinstance(m.content, str) and m.content.startswith(LTM_HEADER)), "")


async def test_thought_logs_do_not_take_recall_slots_from_turns():
    """실서버에서 본 실패: 사고 로그가 사용자 말을 다시 적어 같은 낱말로 더 최근에 걸리고, 턴 일화는 밀려났다."""
    store = InMemoryItemStore()
    memory = MemoryService(store, stm_turns=3)
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
