"""Open-loop 스토어(Tier 2 C1) 단위 테스트."""
from __future__ import annotations

import pytest

from jarvis.agent_layer.openloop import (
    InMemoryOpenLoopStore,
    OpenLoop,
    OpenLoopStore,
    normalize_description,
)


def test_store_satisfies_protocol():
    assert isinstance(InMemoryOpenLoopStore(), OpenLoopStore)


@pytest.mark.asyncio
async def test_add_and_get():
    store = InMemoryOpenLoopStore()
    loop = OpenLoop(description="배포 결과 공유", origin_session="s1")
    lid = await store.add(loop)
    got = await store.get(lid)
    assert got is not None and got.description == "배포 결과 공유"
    assert got.status == "open"


@pytest.mark.asyncio
async def test_add_unique_dedups_open_same_session():
    store = InMemoryOpenLoopStore()
    first = await store.add_unique(OpenLoop(description="배포  결과 공유", origin_session="s1"))
    # 공백/대소문자만 다른 중복 → 추가 안 함.
    dup = await store.add_unique(OpenLoop(description="배포 결과 공유", origin_session="s1"))
    assert first is not None
    assert dup is None
    assert len(await store.all()) == 1


@pytest.mark.asyncio
async def test_add_unique_allows_other_session_and_other_desc():
    store = InMemoryOpenLoopStore()
    await store.add_unique(OpenLoop(description="A 작업", origin_session="s1"))
    other_session = await store.add_unique(OpenLoop(description="A 작업", origin_session="s2"))
    other_desc = await store.add_unique(OpenLoop(description="B 작업", origin_session="s1"))
    assert other_session is not None
    assert other_desc is not None
    assert len(await store.all()) == 3


@pytest.mark.asyncio
async def test_add_unique_ignores_blank():
    store = InMemoryOpenLoopStore()
    assert await store.add_unique(OpenLoop(description="   ", origin_session="s1")) is None


@pytest.mark.asyncio
async def test_list_open_filters_status_and_session():
    store = InMemoryOpenLoopStore()
    a = await store.add(OpenLoop(description="열림1", origin_session="s1"))
    await store.add(OpenLoop(description="열림2", origin_session="s2"))
    done = await store.add(OpenLoop(description="완료됨", origin_session="s1"))
    await store.update_status(done, "done")

    s1_open = await store.list_open(session_id="s1")
    assert [x.id for x in s1_open] == [a]  # done·다른세션 제외

    all_open = await store.list_open()
    assert len(all_open) == 2  # 세션 무관 열린 항목


@pytest.mark.asyncio
async def test_update_status_validation():
    store = InMemoryOpenLoopStore()
    lid = await store.add(OpenLoop(description="x"))
    assert await store.update_status(lid, "done") is True
    assert (await store.get(lid)).status == "done"
    assert await store.update_status(lid, "bogus") is False
    assert await store.update_status("nonexistent", "done") is False


def test_normalize_description():
    assert normalize_description("  배포   결과 ") == "배포 결과"
    assert normalize_description("ABC") == "abc"
