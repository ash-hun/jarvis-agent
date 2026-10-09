"""작업 기억: 창 자르기, 컴팩션 persist(재요약 없음), 되뇌기, 메모, 미들웨어 어댑터."""

import pytest

from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
from jarvis.memory import MemoryManager, MemoryScope
from jarvis.memory.consolidation import llm_summarizer
from jarvis.memory.eval.probe import count_llm_calls
from jarvis.memory.middleware import MemoryMiddlewareAdapter
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.working import InMemoryWorkingStore, WorkingState, WorkingStore, apply_window, cut_at_user_boundary
from jarvis.memory.working.window import SUMMARY_HEADER
from jarvis.model_layer.types import AssistantMessage, TextContent, ToolResultMessage, UserMessage

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


def _manager(model, **kw) -> MemoryManager:
    return MemoryManager(
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
    from jarvis.model_layer.types import ModelConfig
    from tests.fixtures.faux_provider import FauxProviderFactory

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
    memory = MemoryManager(InMemoryItemStore(), window_size=3)
    out = await memory.observe(_history(10, chars=5), CTX)
    assert len(out) <= 3 and out[0].role == "user"


# ── 회상 주입과 되뇌기 ───────────────────────────────────────────────────────


async def test_recall_block_is_injected_and_rehearsal_counted():
    memory = MemoryManager(InMemoryItemStore())
    item_id = await memory.remember("선호 음료: 커피", source="explicit", scope=SCOPE)

    out = await memory.observe([_u("선호 음료 뭐였지")], CTX)
    # 의미 사실은 고정 블록으로 항상 들어가고, 회상 블록은 거기 없는 것만 싣는다
    assert out[0].content.startswith("[핵심 사실]") and "커피" in out[0].content
    assert not any(m.content.startswith("[장기 기억]") for m in out)
    assert (await memory.working_state(SCOPE)).rehearsal == {item_id: 1}

    await memory.observe([_u("선호 음료 뭐였지"), _a("커피"), _u("선호 음료 다시")], CTX)
    assert (await memory.working_state(SCOPE)).rehearsal == {item_id: 2}


async def test_notes_are_session_scoped():
    memory = MemoryManager(InMemoryItemStore())
    await memory.add_note("메모 1", scope=SCOPE)
    await memory.add_note("메모 2", scope=SCOPE)
    assert (await memory.working_state(SCOPE)).notes == ["메모 1", "메모 2"]
    assert (await memory.working_state(SCOPE.with_session("s2"))).notes == []


# ── 미들웨어 어댑터 ──────────────────────────────────────────────────────────


async def test_adapter_routes_chain_hooks_to_manager():
    memory = MemoryManager(InMemoryItemStore(), fixed_facts=0)
    await memory.remember("프로젝트 마감: 금요일", source="explicit", scope=SCOPE)
    chain = MemoryMiddlewareChain(stages=[MemoryMiddlewareAdapter(memory)])

    out = await chain.transform([_u("프로젝트 마감 언제")], CTX)
    assert out[0].content.startswith("[장기 기억]") and "금요일" in out[0].content

    recalled = await chain.retrieve("프로젝트 마감", CTX, limit=5)
    assert [m.content for m in recalled] == ["프로젝트 마감: 금요일"]

    await chain.store(_a("저장되지 않는다"), CTX)
    assert len(await memory.recent(scope=SCOPE)) == 1

    await memory.add_note("n", scope=SCOPE)
    await chain.clear(CTX)
    assert (await memory.working_state(SCOPE)).notes == []


@pytest.mark.parametrize("ctx", [{"session_id": "s1"}, {}])
async def test_adapter_without_user_in_context_uses_local_scope(ctx):
    memory = MemoryManager(InMemoryItemStore())
    await memory.remember("로컬 기억", source="explicit", scope=MemoryScope(user_id="local"))
    out = await MemoryMiddlewareAdapter(memory).transform([_u("로컬 기억 찾기")], ctx)
    assert "로컬 기억" in out[0].content
