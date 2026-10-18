"""/remember slash command 단위 테스트."""
import pytest

from jarvis.core.slash.remember_cmd import make_remember_handler
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService


@pytest.fixture
def ltm():
    return MemoryService(InMemoryItemStore())


@pytest.fixture
def handler(ltm):
    return make_remember_handler(ltm)


# ── 저장 ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remember_save(handler, ltm):
    result = await handler("Jarvis 프로젝트 메모리 레이어 개발 중")
    assert "[Memory]" in result
    assert "저장" in result

    recent = await ltm.recent()
    assert len(recent) == 1
    assert "Jarvis" in recent[0].content


@pytest.mark.asyncio
async def test_remember_save_returns_short_id(handler):
    result = await handler("테스트 저장")
    # id의 앞 8자리만 표시
    assert "(id:" in result


# ── list ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remember_list_empty(handler):
    result = await handler("list")
    assert "없습니다" in result


@pytest.mark.asyncio
async def test_remember_list_shows_entries(handler, ltm):
    await ltm.remember("항목 A", source="explicit")
    await ltm.remember("항목 B", source="explicit")

    result = await handler("list")
    assert "항목 A" in result
    assert "항목 B" in result


# ── search ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remember_search_found(handler, ltm):
    await ltm.remember("FastAPI 공부 중", source="explicit")
    result = await handler("search FastAPI")
    assert "FastAPI" in result


@pytest.mark.asyncio
async def test_remember_search_not_found(handler, ltm):
    await ltm.remember("FastAPI 공부 중", source="explicit")
    result = await handler("search Django")
    assert "없습니다" in result


@pytest.mark.asyncio
async def test_remember_search_empty_query(handler):
    result = await handler("search ")
    assert "키워드" in result


# ── forget ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remember_forget(handler, ltm):
    entry_id = await ltm.remember("삭제 대상", source="explicit")

    result = await handler(f"forget {entry_id}")
    assert "삭제" in result

    recent = await ltm.recent()
    assert all(r.id != entry_id for r in recent)


@pytest.mark.asyncio
async def test_remember_forget_empty_id(handler):
    result = await handler("forget ")
    assert "id" in result


# ── usage (빈 args) ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remember_empty_shows_usage(handler):
    result = await handler("")
    assert "사용법" in result
    assert "/remember" in result


@pytest.mark.asyncio
async def test_remember_conflicts_lists_marked_pairs(handler, ltm):
    from jarvis.memory import MemoryScope

    assert "없습니다" in await handler("conflicts")
    a = await ltm.remember("출근 수단: 지하철로 출근", source="explicit", scope=MemoryScope(user_id="local"))
    b = await ltm.remember("통근 방법: 지하철로 출근", source="explicit", scope=MemoryScope(user_id="local"))
    item = await ltm.get(a)
    item.metadata["conflicts_with"] = [b]
    await ltm.store.store(item)

    out = await handler("conflicts")
    assert "어긋날 수 있는" in out and a[:8] in out and b[:8] in out
