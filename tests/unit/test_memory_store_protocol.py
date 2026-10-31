"""memory 기능의 장기 기억 저장소 기본 클래스: 구현체의 상속, 기본 동작, 질의 토큰화."""

import pytest
from datetime import datetime

from jarvis.memory.stores.store_protocol import ItemStore, tokens_of
from jarvis.memory import MemoryItem, MemoryKind, MemoryScope
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.stores.postgres import PostgresItemStore

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


def _item(content: str) -> MemoryItem:
    return MemoryItem(content=content, kind=MemoryKind.SEMANTIC, scope=SCOPE)


@pytest.mark.parametrize(
    "store",
    [InMemoryItemStore(), PostgresItemStore(dsn="postgresql://unused")],
    ids=["in_memory", "postgres_not_connected"],
)
def test_concrete_item_stores_inherit_the_base(store):
    assert isinstance(store, ItemStore)


async def test_item_store_base_is_a_working_in_memory_store():
    store = ItemStore()
    old, new = _item("거주지: 부산"), _item("거주지: 서울")
    at = datetime(2024, 1, 1)

    assert await store.store(old) == old.id
    await store.store(new)
    assert await store.get(old.id) is old
    assert {i.id for i in await store.search("거주지", SCOPE)} == {old.id, new.id}
    await store.supersede(old.id, new.id)
    assert [i.id for i in await store.recent(SCOPE)] == [new.id]
    await store.touch([new.id, "missing"], at)
    assert new.last_accessed == at
    await store.delete(new.id)
    assert await store.get(new.id) is None
    await store.clear()
    assert await store.get(old.id) is None


async def test_item_store_search_without_tokens_or_vector_is_empty():
    store = ItemStore()
    await store.store(_item("anything"))

    assert await store.search("   ", SCOPE) == []


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
