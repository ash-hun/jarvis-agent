"""multi_agent: SharedBlackboard 의 읽기, 쓰기, 스냅샷, 구독, 삭제를 검증한다."""

import pytest
import asyncio

from jarvis.core.multi_agent.blackboard import SharedBlackboard


async def test_read_returns_latest_value_or_none():
    bb = SharedBlackboard()

    await bb.write("k", "v1", author="a")
    await bb.write("k", "v2", author="b")

    assert bb.read("k") == "v2"
    assert bb.read("ghost") is None


async def test_read_entry_keeps_author_and_written_at():
    bb = SharedBlackboard()

    await bb.write("k", "v", author="researcher")

    entry = bb.read_entry("k")
    assert entry is not None
    assert entry.author == "researcher"
    assert entry.written_at is not None


async def test_snapshot_returns_detached_copy_of_all_keys():
    bb = SharedBlackboard()
    await bb.write("a", 1, author="x")
    await bb.write("b", 2, author="y")

    snap = bb.snapshot()
    snap["a"] = "mutated"

    assert snap == {"a": "mutated", "b": 2}
    assert bb.read("a") == 1


async def test_watch_receives_only_writes_to_its_key():
    bb = SharedBlackboard()
    q = await bb.watch("result")

    await bb.write("other", "irrelevant", author="x")
    await bb.write("result", "done", author="analyst")

    entry = await asyncio.wait_for(q.get(), timeout=1.0)
    assert (entry.key, entry.value, entry.author) == ("result", "done", "analyst")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.05)


async def test_watch_notifies_every_watcher_of_the_key():
    bb = SharedBlackboard()
    q1 = await bb.watch("k")
    q2 = await bb.watch("k")

    await bb.write("k", "broadcast", author="x")

    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1.value == e2.value == "broadcast"


async def test_watch_all_receives_every_write():
    bb = SharedBlackboard()
    q = await bb.watch_all()

    await bb.write("k1", "v1", author="a1")
    await bb.write("k2", "v2", author="a2")

    entries = [await asyncio.wait_for(q.get(), timeout=1.0) for _ in range(2)]
    assert {e.key for e in entries} == {"k1", "k2"}


@pytest.mark.parametrize(("key", "remaining"), [("a", {"b": 2}), (None, {})])
async def test_clear_removes_one_key_or_all(key, remaining):
    bb = SharedBlackboard()
    await bb.write("a", 1, author="x")
    await bb.write("b", 2, author="x")

    bb.clear(key)

    assert bb.snapshot() == remaining
    assert len(bb) == len(remaining)
    assert "a" not in bb
    assert ("b" in bb) is ("b" in remaining)
