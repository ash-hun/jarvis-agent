"""EpisodicSummarizer + CompactionMiddleware LTM 연동 단위 테스트."""
from __future__ import annotations

import pytest

from jarvis.agent_layer.memory.backends.in_memory_stm import InMemorySTMBackend
from jarvis.agent_layer.memory.compaction import CompactionMiddleware
from jarvis.agent_layer.memory.episodic import EpisodicSummarizer
from jarvis.memory.manager import MemoryManager
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.model_layer.types import UserMessage

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def ltm():
    return MemoryManager(InMemoryItemStore())


@pytest.fixture
def stm():
    return InMemorySTMBackend()


def _user_msg(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


# ── EpisodicSummarizer ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_episodic_save_session_stores_to_ltm(faux_model_with_response, ltm):
    model = faux_model_with_response("세션 요약: 사용자가 Python 기초를 배웠습니다.")
    summarizer = EpisodicSummarizer(model=model, memory=ltm)

    msgs = [_user_msg("Python 기초를 배우고 싶어"), _user_msg("변수 선언 방법 알려줘")]
    entry_id = await summarizer.save_session("test-session", msgs)

    assert entry_id is not None
    recent = await ltm.recent()
    assert len(recent) == 1
    assert recent[0].source == "session_end"
    assert recent[0].session_id == "test-session"
    assert "Python" in recent[0].content or "요약" in recent[0].content


@pytest.mark.asyncio
async def test_episodic_empty_messages_returns_none(faux_model_with_response, ltm):
    model = faux_model_with_response("요약")
    summarizer = EpisodicSummarizer(model=model, memory=ltm)

    result = await summarizer.save_session("test-session", [])
    assert result is None
    assert await ltm.recent() == []


@pytest.mark.asyncio
async def test_episodic_saves_entry_id(faux_model_with_response, ltm):
    model = faux_model_with_response("요약 내용")
    summarizer = EpisodicSummarizer(model=model, memory=ltm)

    entry_id = await summarizer.save_session("s1", [_user_msg("안녕")])
    assert isinstance(entry_id, str)
    assert len(entry_id) == 32  # MemoryItem.id 는 uuid4().hex (32자)


@pytest.mark.asyncio
async def test_episodic_multiple_sessions_stored_separately(faux_model_with_response, ltm):
    model = faux_model_with_response("요약")
    summarizer = EpisodicSummarizer(model=model, memory=ltm)

    await summarizer.save_session("session-a", [_user_msg("첫 번째 세션")])
    await summarizer.save_session("session-b", [_user_msg("두 번째 세션")])

    recent = await ltm.recent()
    assert len(recent) == 2
    session_ids = {e.session_id for e in recent}
    assert "session-a" in session_ids
    assert "session-b" in session_ids


# ── CompactionMiddleware + LTM 연동 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_compaction_saves_summary_to_ltm(faux_model_with_response, ltm):
    """컨텍스트 임계값 초과 시 요약이 LTM에 자동 저장된다."""
    model = faux_model_with_response("압축 요약: 초기 대화 내용 요약")
    middleware = CompactionMiddleware(
        model=model,
        threshold_chars=10,  # 매우 낮게 설정해 압축 강제 발동
        keep_recent=1,
        memory=ltm,
    )

    msgs = [_user_msg("첫 번째 메시지"), _user_msg("두 번째 메시지"), _user_msg("세 번째 메시지")]
    context = {"session_id": "compact-session"}
    await middleware.transform(msgs, context)

    recent = await ltm.recent()
    assert len(recent) == 1
    assert recent[0].source == "auto_summary"
    assert recent[0].session_id == "compact-session"


@pytest.mark.asyncio
async def test_compaction_no_ltm_does_not_raise(faux_model_with_response):
    """memory=None 이면 LTM 저장 없이 정상 압축."""
    model = faux_model_with_response("요약")
    middleware = CompactionMiddleware(
        model=model,
        threshold_chars=10,
        keep_recent=1,
        memory=None,  # LTM 미연결
    )

    msgs = [_user_msg("메시지 A"), _user_msg("메시지 B"), _user_msg("메시지 C")]
    result = await middleware.transform(msgs, {"session_id": "s1"})
    # 압축 후 keep_recent=1 + summary 메시지 = 2개
    assert len(result) == 2


@pytest.mark.asyncio
async def test_compaction_below_threshold_no_ltm_write(faux_model_with_response, ltm):
    """임계값 미만이면 압축 없이 LTM에도 저장하지 않는다."""
    model = faux_model_with_response("요약")
    middleware = CompactionMiddleware(
        model=model,
        threshold_chars=1_000_000,  # 매우 높게 설정 — 압축 비발동
        keep_recent=10,
        memory=ltm,
    )

    msgs = [_user_msg("짧은 메시지")]
    result = await middleware.transform(msgs, {"session_id": "s1"})

    assert result == msgs
    assert await ltm.recent() == []


@pytest.mark.asyncio
async def test_compaction_keeps_recent_messages(faux_model_with_response, ltm):
    """압축 후 keep_recent 개수만큼의 최신 메시지가 보존된다."""
    model = faux_model_with_response("요약")
    middleware = CompactionMiddleware(
        model=model,
        threshold_chars=10,
        keep_recent=2,
        memory=ltm,
    )

    msgs = [
        _user_msg("오래된 메시지 1"),
        _user_msg("오래된 메시지 2"),
        _user_msg("최신 메시지 A"),
        _user_msg("최신 메시지 B"),
    ]
    result = await middleware.transform(msgs, {"session_id": "s1"})

    # summary_msg + 최신 2개 = 3개
    assert len(result) == 3
    assert result[-1].content == "최신 메시지 B"
    assert result[-2].content == "최신 메시지 A"


# ── 요약 LLM 실패 ──────────────────────────────────────────────────────────────

@pytest.fixture
def faux_model_error():
    from jarvis.model_layer.registry import get_default_registry
    from jarvis.model_layer.types import ModelConfig
    from tests.fixtures.faux_provider import FauxProviderFactory

    get_default_registry()._providers["faux"] = FauxProviderFactory.error()
    return ModelConfig(provider="faux", model="faux-model")


@pytest.mark.asyncio
async def test_episodic_skips_store_when_summary_llm_fails(faux_model_error, ltm):
    summarizer = EpisodicSummarizer(model=faux_model_error, memory=ltm)

    entry_id = await summarizer.save_session("s", [_user_msg("hi")])

    assert entry_id is None
    assert await ltm.recent() == []


@pytest.mark.asyncio
async def test_compaction_keeps_history_when_summary_llm_fails(faux_model_error, ltm):
    middleware = CompactionMiddleware(model=faux_model_error, threshold_chars=10, keep_recent=1, memory=ltm)
    msgs = [_user_msg("a"), _user_msg("b"), _user_msg("c")]

    out = await middleware.transform(msgs, {"session_id": "s"})

    assert out == msgs  # 압축 건너뜀 — 빈 요약으로 히스토리를 날리지 않는다
    assert await ltm.recent() == []
