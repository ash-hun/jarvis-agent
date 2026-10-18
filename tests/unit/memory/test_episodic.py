"""EpisodicSummarizer 단위 테스트. 세션 종료 요약이 그 세션 범위의 일화로 저장된다."""
import pytest

from jarvis.memory.consolidation.episodic import EpisodicSummarizer
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
from jarvis.model_layer.types import UserMessage

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def ltm():
    return MemoryService(InMemoryItemStore())


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


# ── 요약 LLM 실패 ──────────────────────────────────────────────────────────────

@pytest.fixture
def faux_model_error():
    from jarvis.model_layer.registry import get_default_registry
    from tests.fixtures.faux_provider import FauxProviderFactory
    from jarvis.model_layer.types import ModelConfig

    get_default_registry()._providers["faux"] = FauxProviderFactory.error()
    return ModelConfig(provider="faux", model="faux-model")


@pytest.mark.asyncio
async def test_episodic_skips_store_when_summary_llm_fails(faux_model_error, ltm):
    summarizer = EpisodicSummarizer(model=faux_model_error, memory=ltm)

    entry_id = await summarizer.save_session("s", [_user_msg("hi")])

    assert entry_id is None
    assert await ltm.recent() == []
