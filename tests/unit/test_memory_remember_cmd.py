"""memory 기능의 /remember 명령: 저장, 목록, 검색, 삭제, 간섭 후보, 지칭 저장 시 가리킨 대화 연결."""

import pytest

from jarvis.model_layer.model_types import AssistantMessage, TextContent, UserMessage
from jarvis.core.slash.remember_cmd import make_remember_handler
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
from jarvis.memory import MemoryKind, MemoryScope
from jarvis.memory.memory_types import REFERENT

SCOPE = MemoryScope(user_id="local")
DEIXIS_SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


class _Repo:
    def __init__(self, messages) -> None:
        self._messages = messages

    async def get_messages(self, session_id: str):
        return self._messages


@pytest.fixture
def ltm():
    return MemoryService(InMemoryItemStore())


@pytest.fixture
def handler(ltm):
    return make_remember_handler(ltm)


async def test_remember_saves_and_shows_short_id(handler, ltm):
    result = await handler("Jarvis 프로젝트 메모리 레이어 개발 중", SCOPE)

    assert "[Memory]" in result and "저장" in result and "(id:" in result
    recent = await ltm.recent(SCOPE)
    assert len(recent) == 1
    assert "Jarvis" in recent[0].content


@pytest.mark.parametrize(
    ("args", "expected"),
    [("", "사용법"), ("", "/remember"), ("list", "없습니다"), ("search ", "키워드"), ("forget ", "id")],
    ids=["usage", "usage_names_command", "list_empty", "search_without_query", "forget_without_id"],
)
async def test_remember_without_needed_input_explains(handler, args, expected):
    assert expected in await handler(args, SCOPE)


async def test_remember_list_shows_entries(handler, ltm):
    await ltm.remember("항목 A", source="explicit", scope=SCOPE)
    await ltm.remember("항목 B", source="explicit", scope=SCOPE)

    result = await handler("list", SCOPE)

    assert "항목 A" in result and "항목 B" in result


@pytest.mark.parametrize(("query", "expected"), [("FastAPI", "FastAPI"), ("Django", "없습니다")])
async def test_remember_search_reports_hit_or_miss(handler, ltm, query, expected):
    await ltm.remember("FastAPI 공부 중", source="explicit", scope=SCOPE)

    assert expected in await handler(f"search {query}", SCOPE)


async def test_remember_forget_removes_entry(handler, ltm):
    entry_id = await ltm.remember("삭제 대상", source="explicit", scope=SCOPE)

    result = await handler(f"forget {entry_id}", SCOPE)

    assert "삭제" in result
    assert all(r.id != entry_id for r in await ltm.recent(SCOPE))


async def test_remember_conflicts_lists_marked_pairs(handler, ltm):
    assert "없습니다" in await handler("conflicts", SCOPE)
    a = await ltm.remember("출근 수단: 지하철로 출근", source="explicit", scope=SCOPE)
    b = await ltm.remember("통근 방법: 지하철로 출근", source="explicit", scope=SCOPE)
    item = await ltm.get(a)
    item.metadata["conflicts_with"] = [b]
    await ltm.store.store(item)

    out = await handler("conflicts", SCOPE)

    assert "어긋날 수 있는" in out and a[:8] in out and b[:8] in out


async def test_remember_links_referent_only_for_deictic_content():
    memory = MemoryService(InMemoryItemStore())
    history = [
        UserMessage(content="커밋 메시지 규칙 정해줘", timestamp=0),
        AssistantMessage(content=[TextContent(text="제목 50자, 본문은 why")], timestamp=0),
    ]
    handler = make_remember_handler(memory, _Repo(history))

    linked = await handler("그거 기억해", DEIXIS_SCOPE)
    plain = await handler("거주지: 서울", DEIXIS_SCOPE)

    assert "가리킨 대화" in linked and "가리킨 대화" not in plain
    items = {i.content: i for i in await memory.recent(DEIXIS_SCOPE, kinds=[MemoryKind.SEMANTIC])}
    assert items["그거 기억해"].metadata[REFERENT] == "커밋 메시지 규칙 정해줘\n제목 50자, 본문은 why"
    assert REFERENT not in items["거주지: 서울"].metadata
