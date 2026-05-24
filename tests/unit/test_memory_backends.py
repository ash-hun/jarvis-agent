"""단기/장기 메모리 백엔드 + 미들웨어 단위 테스트."""
from __future__ import annotations

import pytest

from jarvis.agent_layer.memory.backends.in_memory_ltm import InMemoryLTMBackend
from jarvis.agent_layer.memory.backends.in_memory_stm import InMemorySTMBackend
from jarvis.agent_layer.memory.backends.protocol import LTMBackend, MemoryEntry, STMBackend
from jarvis.agent_layer.memory.long_term import LongTermMemory
from jarvis.agent_layer.memory.short_term import ShortTermMemory
from jarvis.model_layer.types import AssistantMessage, TextContent, UserMessage

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def stm_backend():
    return InMemorySTMBackend()


@pytest.fixture
def ltm_backend():
    return InMemoryLTMBackend()


def _user_msg(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


def _asst_msg(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)], timestamp=0)


# ── Protocol conformance ───────────────────────────────────────────────────────

def test_stm_backend_satisfies_protocol(stm_backend):
    assert isinstance(stm_backend, STMBackend)


def test_ltm_backend_satisfies_protocol(ltm_backend):
    assert isinstance(ltm_backend, LTMBackend)


# ── InMemorySTMBackend ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stm_append_and_load(stm_backend):
    msg1 = _user_msg("hello")
    msg2 = _asst_msg("hi there")
    await stm_backend.append("s1", msg1)
    await stm_backend.append("s1", msg2)

    msgs = await stm_backend.load("s1")
    assert len(msgs) == 2
    assert msgs[0].content == "hello"
    assert msgs[1].content[0].text == "hi there"


@pytest.mark.asyncio
async def test_stm_sessions_are_isolated(stm_backend):
    await stm_backend.append("s1", _user_msg("session 1"))
    await stm_backend.append("s2", _user_msg("session 2"))

    assert len(await stm_backend.load("s1")) == 1
    assert len(await stm_backend.load("s2")) == 1
    assert (await stm_backend.load("s1"))[0].content == "session 1"


@pytest.mark.asyncio
async def test_stm_clear(stm_backend):
    await stm_backend.append("s1", _user_msg("msg"))
    await stm_backend.clear("s1")
    assert await stm_backend.load("s1") == []


@pytest.mark.asyncio
async def test_stm_load_empty(stm_backend):
    assert await stm_backend.load("nonexistent") == []


# ── InMemoryLTMBackend ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ltm_store_and_get_recent(ltm_backend):
    e = MemoryEntry(content="Python 배우기", source="explicit")
    await ltm_backend.store(e)

    recent = await ltm_backend.get_recent(limit=5)
    assert len(recent) == 1
    assert recent[0].content == "Python 배우기"
    assert recent[0].source == "explicit"


@pytest.mark.asyncio
async def test_ltm_search_keyword(ltm_backend):
    await ltm_backend.store(MemoryEntry(content="LangChain 튜토리얼", source="explicit"))
    await ltm_backend.store(MemoryEntry(content="Python 기초 문법", source="explicit"))

    results = await ltm_backend.search("LangChain")
    assert len(results) == 1
    assert "LangChain" in results[0].content


@pytest.mark.asyncio
async def test_ltm_search_no_match(ltm_backend):
    await ltm_backend.store(MemoryEntry(content="FastAPI 정리", source="explicit"))
    results = await ltm_backend.search("Django")
    assert results == []


@pytest.mark.asyncio
async def test_ltm_delete(ltm_backend):
    e = MemoryEntry(content="삭제할 항목", source="explicit")
    entry_id = await ltm_backend.store(e)
    await ltm_backend.delete(entry_id)

    recent = await ltm_backend.get_recent()
    assert all(r.id != entry_id for r in recent)


@pytest.mark.asyncio
async def test_ltm_clear_all(ltm_backend):
    for i in range(3):
        await ltm_backend.store(MemoryEntry(content=f"항목 {i}", source="explicit"))
    await ltm_backend.clear_all()
    assert await ltm_backend.get_recent() == []


@pytest.mark.asyncio
async def test_ltm_store_returns_id(ltm_backend):
    e = MemoryEntry(content="테스트", source="explicit")
    returned_id = await ltm_backend.store(e)
    assert returned_id == e.id


# ── ShortTermMemory middleware ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_short_term_store_and_retrieve(stm_backend):
    stm = ShortTermMemory(stm_backend)
    ctx = {"session_id": "s1"}

    await stm.store(_user_msg("테스트"), ctx)
    msgs = await stm.retrieve("", ctx, limit=10)
    assert len(msgs) == 1
    assert msgs[0].content == "테스트"


@pytest.mark.asyncio
async def test_short_term_transform_is_passthrough(stm_backend):
    stm = ShortTermMemory(stm_backend)
    msgs = [_user_msg("hello")]
    result = await stm.transform(msgs, {})
    assert result == msgs


@pytest.mark.asyncio
async def test_short_term_clear(stm_backend):
    stm = ShortTermMemory(stm_backend)
    ctx = {"session_id": "s1"}
    await stm.store(_user_msg("msg"), ctx)
    await stm.clear(ctx)
    assert await stm.retrieve("", ctx) == []


# ── LongTermMemory middleware ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_long_term_transform_injects_memory(ltm_backend):
    await ltm_backend.store(MemoryEntry(content="Jarvis 개발 중", source="explicit"))

    ltm = LongTermMemory(ltm_backend, inject_limit=3)
    msgs = [_user_msg("Jarvis 진행 상황 알려줘")]
    result = await ltm.transform(msgs, {})

    assert len(result) == 2
    assert "[장기 기억]" in result[0].content
    assert "Jarvis 개발 중" in result[0].content


@pytest.mark.asyncio
async def test_long_term_transform_no_match_returns_unchanged(ltm_backend):
    await ltm_backend.store(MemoryEntry(content="Python 기초", source="explicit"))

    ltm = LongTermMemory(ltm_backend, inject_limit=3)
    msgs = [_user_msg("Django 배우고 싶어")]
    result = await ltm.transform(msgs, {})
    assert result == msgs


@pytest.mark.asyncio
async def test_long_term_transform_no_user_message(ltm_backend):
    await ltm_backend.store(MemoryEntry(content="테스트 항목", source="explicit"))
    ltm = LongTermMemory(ltm_backend)
    # user 메시지가 없는 경우 LTM 주입 없이 원본 반환
    msgs: list = []
    result = await ltm.transform(msgs, {})
    assert result == msgs


@pytest.mark.asyncio
async def test_long_term_store_is_noop(ltm_backend):
    ltm = LongTermMemory(ltm_backend)
    await ltm.store(_user_msg("should not be saved"), {})
    assert await ltm_backend.get_recent() == []


@pytest.mark.asyncio
async def test_long_term_clear_is_noop(ltm_backend):
    await ltm_backend.store(MemoryEntry(content="보존되어야 함", source="explicit"))
    ltm = LongTermMemory(ltm_backend)
    await ltm.clear({})
    assert len(await ltm_backend.get_recent()) == 1
