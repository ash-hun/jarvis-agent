"""메모리 기본 단위: 항목 모델, 범위, 일화 정책, 작업 기억 상태, 단서 겹침, 컴팩션 요약기, 벤치마크 어댑터 경계."""

import pytest
from datetime import datetime

from jarvis.memory.consolidation.compaction import (
    llm_summarizer,
    render_messages,
    summarize_messages,
    system_prompt_for,
)
from jarvis.memory.scope import (
    LOCAL_USER,
    MAIN_AGENT,
    TASK_AGENT,
    MemoryScope,
    scope_from_context,
    task_scope,
)
from jarvis.model_layer.types import AssistantMessage, LLMContext, TextContent, UserMessage
from jarvis.memory.eval.adapters.longmemeval import parse_longmemeval
from jarvis.memory.working.in_memory import InMemoryWorkingStore
from jarvis.memory.working.state import MAX_NOTES, WorkingState
from jarvis.memory.long_term.episodic import prepare_episode
from jarvis.memory.eval.adapters.locomo import parse_locomo
from jarvis.memory.types import MemoryItem, MemoryKind
from jarvis.memory.retrieval.cues import cue_overlap
from jarvis.memory.stores.protocol import tokens_of

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


# ── types ────────────────────────────────────────────────────────────────────


def test_memory_item_defaults_and_session_property():
    a = MemoryItem(content="x", kind=MemoryKind.EPISODIC, scope=SCOPE)
    b = MemoryItem(content="x", kind=MemoryKind.EPISODIC, scope=SCOPE)
    assert a.id != b.id and len(a.id) == 32
    assert (a.author, a.importance, a.rehearsal_count) == ("agent", 0.5, 0)
    assert a.session_id == "s1"
    a.tags.append("t")
    a.metadata["k"] = 1
    assert b.tags == [] and b.metadata == {}  # 기본값 목록과 dict 를 항목끼리 공유하지 않는다


# ── scope ────────────────────────────────────────────────────────────────────


def test_with_session_keeps_owner():
    assert SCOPE.with_session(None) == MemoryScope(user_id="u1", agent_id="main")


def test_task_scope_depends_only_on_user_and_task():
    assert task_scope("u1", "t9") == MemoryScope(user_id="u1", agent_id=TASK_AGENT, session_id="task_t9")
    assert task_scope(None, "t9").user_id == LOCAL_USER


def test_scope_from_context_uses_only_what_the_caller_passed():
    local = MemoryScope(user_id=LOCAL_USER, agent_id=MAIN_AGENT, session_id="s")
    assert scope_from_context({"session_id": "s"}) == local
    explicit = scope_from_context({"user_id": "u2", "agent_id": "a2", "session_id": "s"})
    assert explicit == MemoryScope(user_id="u2", agent_id="a2", session_id="s")


# ── long_term.episodic ───────────────────────────────────────────────────────


def test_prepare_episode_sets_occurred_at_once():
    item = MemoryItem(content="회의", kind=MemoryKind.EPISODIC, scope=SCOPE, created_at=datetime(2024, 1, 2))
    assert prepare_episode(item).occurred_at == datetime(2024, 1, 2)
    item.occurred_at = datetime(2023, 12, 31)
    assert prepare_episode(item).occurred_at == datetime(2023, 12, 31)  # 다시 불러도 사건 시각을 덮지 않는다


# ── working.state / working.in_memory ────────────────────────────────────────


def test_working_state_notes_are_capped_and_rehearsal_counts():
    state = WorkingState(scope=SCOPE)
    for i in range(MAX_NOTES + 5):
        state.add_note(f"n{i}")
    assert len(state.notes) == MAX_NOTES and state.notes[0] == "n5"
    assert [state.rehearse("a"), state.rehearse("a"), state.rehearse("b")] == [1, 2, 1]


async def test_in_memory_working_store_hands_out_copies():
    store = InMemoryWorkingStore()
    state = WorkingState(scope=SCOPE)
    state.add_note("first")
    await store.save(state)
    state.add_note("after save")  # save 뒤 원본을 고쳐도 저장본은 그대로
    loaded = await store.load(SCOPE)
    loaded.rehearse("x")  # save 하지 않은 수정은 반영되지 않는다
    again = await store.load(SCOPE)
    assert again.notes == ["first"] and again.rehearsal == {}


# ── retrieval.cues ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("item_scope", "expected"),
    [
        (SCOPE, 0.5),  # 같은 세션: context 1.0, 태그 없음
        (SCOPE.with_session("other"), 0.25),  # 같은 에이전트: context 0.5
        (MemoryScope(user_id="u1", agent_id="coder"), 0.0),
    ],
)
def test_cue_overlap_context_part(item_scope, expected):
    item = MemoryItem(content="x", kind=MemoryKind.SEMANTIC, scope=item_scope)
    assert cue_overlap(item, SCOPE, "아무 질의") == expected


def test_cue_overlap_tag_part_splits_on_colon():
    item = MemoryItem(content="x", kind=MemoryKind.SEMANTIC, scope=SCOPE, tags=["key:거주지"])
    assert cue_overlap(item, SCOPE, "거주지 어디") == (1.0 + 0.5) / 2
    assert cue_overlap(item, SCOPE, "") == 0.5


# ── consolidation.compaction ─────────────────────────────────────────────────


def test_render_messages_tags_role_and_serializes_blocks():
    text = render_messages([UserMessage(content="안녕"), AssistantMessage(content=[TextContent(text="네")])])
    first, second = text.split("\n")
    assert first == "[user] 안녕"
    assert second.startswith("[assistant] {") and '"네"' in second


async def test_summarize_messages_continues_prior_summary(monkeypatch, faux_model):
    seen: list[LLMContext] = []

    async def fake_stream(model, ctx, options):
        seen.append(ctx)
        return AssistantMessage(content=[TextContent(text="  새 요약  ")])

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)
    assert await summarize_messages(faux_model, [UserMessage(content="hi")], prior="옛 요약") == "새 요약"
    prompt = seen[0].messages[0].content
    assert isinstance(prompt, str) and prompt.startswith("이전 요약:\n옛 요약\n\n") and "[user] hi" in prompt
    assert seen[0].system_prompt == system_prompt_for([UserMessage(content="hi")])


async def test_summarize_messages_none_on_error_and_placeholder_on_blank(monkeypatch, faux_model):
    replies = [
        AssistantMessage(content=[], error_message="boom"),
        AssistantMessage(content=[TextContent(text="   ")]),
    ]

    async def fake_stream(model, ctx, options):
        return replies.pop(0)

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)
    summarize = llm_summarizer(faux_model)
    assert await summarize([UserMessage(content="hi")], None) is None
    assert await summarize([UserMessage(content="hi")], None) == "[summary unavailable]"


# ── eval.adapters 경계 ───────────────────────────────────────────────────────


def test_longmemeval_missing_ids_and_dates_fall_back():
    [q] = parse_longmemeval([{
        "question_id": 7,
        "question": "q?",
        "haystack_sessions": [[{"content": "hello", "has_answer": True}], [{"role": "assistant", "content": "x"}]],
        "haystack_session_ids": ["only-one"],
    }])
    assert q.question_id == "7" and q.question_type == "unknown" and q.answer == ""
    assert [s.session_id for s in q.sessions] == ["only-one", "session_1"]
    assert [s.date for s in q.sessions] == ["", ""]
    assert q.sessions[0].turns[0].role == "user" and q.evidence_turn_ids == {"only-one#0"}
    assert q.evidence_session_ids == set()


def test_locomo_orders_sessions_numerically_and_drops_unknown_evidence():
    [q] = parse_locomo([{
        "sample_id": "c",
        "conversation": {
            "session_10": [{"speaker": "A", "text": "ten", "dia_id": "D10:1"}],
            "session_2": [{"speaker": "B", "text": "two", "dia_id": "D2:1"}],
            "session_2_date_time": "1:56 pm on 8 May, 2023",
        },
        "qa": [{"question": "q", "answer": 3, "category": 9, "evidence": ["D2:1", "D99:9"]}],
    }])
    assert [s.session_id for s in q.sessions] == ["c:session_2", "c:session_10"]
    assert q.sessions[0].date == "1:56 pm on 8 May, 2023" and q.sessions[1].date == ""
    assert q.question_type == "unknown" and q.answer == "3"
    assert q.evidence_turn_ids == {"D2:1", "D99:9"} and q.evidence_session_ids == {"c:session_2"}


def test_summary_language_follows_conversation_text() -> None:
    from jarvis.memory.consolidation.compaction import conversation_language
    from jarvis.model_layer.types import AssistantMessage, TextContent

    ko = [UserMessage(content="예산은 1200만원이야"), AssistantMessage(content=[TextContent(text="알겠습니다")])]
    en = [UserMessage(content="The budget is $40k"), AssistantMessage(content=[TextContent(text="Got it")])]
    # 어시스턴트 메시지의 JSON 키는 세지 않는다
    assert conversation_language(ko) == "ko"
    assert conversation_language(en) == "en"
    # 코드와 영어 낱말이 많은 한국어 개발 대화도 한국어다
    assert conversation_language([UserMessage(content="pytest 로 tests/unit/test_api.py 돌려줘")]) == "ko"
    assert "한국어로 쓴다" in system_prompt_for(ko)
    assert "English" in system_prompt_for(en)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("서울에서?", ["서울"]),
        ("'회의' 언제야", ["회의", "언제야"]),
        ("배포 - 금요일", ["배포", "금요일"]),  # 문장부호만인 토큰은 모든 항목에 걸리므로 버린다
        ("e-mail 보내", ["e-mail", "보내"]),  # 가운데 문장부호는 남긴다
        ("회의가 끝나면", ["회의", "끝나면"]),
    ],
)
def test_tokens_of_strips_edge_punctuation_before_josa(query, expected):
    assert tokens_of(query) == expected
