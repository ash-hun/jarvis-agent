"""SharedBlackboard 단위 테스트."""

import asyncio

import pytest

from jarvis.core.multi_agent.blackboard import SharedBlackboard


@pytest.mark.asyncio
async def test_write_and_read():
    bb = SharedBlackboard()
    await bb.write("k", "v", author="agent1")
    assert bb.read("k") == "v"


@pytest.mark.asyncio
async def test_read_missing_key_returns_none():
    assert SharedBlackboard().read("ghost") is None


@pytest.mark.asyncio
async def test_overwrite():
    bb = SharedBlackboard()
    await bb.write("k", "v1", author="a")
    await bb.write("k", "v2", author="b")
    assert bb.read("k") == "v2"


@pytest.mark.asyncio
async def test_snapshot_all_keys():
    bb = SharedBlackboard()
    await bb.write("a", 1, author="x")
    await bb.write("b", 2, author="y")
    snap = bb.snapshot()
    assert snap == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_snapshot_is_copy():
    """snapshot()은 내부 상태와 분리된 dict를 반환한다."""
    bb = SharedBlackboard()
    await bb.write("k", "v", author="x")
    snap = bb.snapshot()
    snap["k"] = "mutated"
    assert bb.read("k") == "v"


@pytest.mark.asyncio
async def test_watch_key_notification():
    bb = SharedBlackboard()
    q = await bb.watch("result")

    await bb.write("result", "done", author="analyst")

    entry = await asyncio.wait_for(q.get(), timeout=1.0)
    assert entry.value == "done"
    assert entry.author == "analyst"
    assert entry.key == "result"


@pytest.mark.asyncio
async def test_watch_key_no_notification_for_other_key():
    bb = SharedBlackboard()
    q = await bb.watch("target")

    await bb.write("other", "irrelevant", author="x")

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.05)


@pytest.mark.asyncio
async def test_watch_all_receives_every_write():
    bb = SharedBlackboard()
    q = await bb.watch_all()

    await bb.write("k1", "v1", author="a1")
    await bb.write("k2", "v2", author="a2")

    entries = []
    for _ in range(2):
        e = await asyncio.wait_for(q.get(), timeout=1.0)
        entries.append(e)

    assert {e.key for e in entries} == {"k1", "k2"}


@pytest.mark.asyncio
async def test_clear_specific_key():
    bb = SharedBlackboard()
    await bb.write("a", 1, author="x")
    await bb.write("b", 2, author="x")
    bb.clear("a")
    assert bb.read("a") is None
    assert bb.read("b") == 2


@pytest.mark.asyncio
async def test_clear_all():
    bb = SharedBlackboard()
    await bb.write("a", 1, author="x")
    await bb.write("b", 2, author="x")
    bb.clear()
    assert bb.snapshot() == {}
    assert len(bb) == 0


@pytest.mark.asyncio
async def test_contains():
    bb = SharedBlackboard()
    await bb.write("present", "yes", author="x")
    assert "present" in bb
    assert "absent" not in bb


@pytest.mark.asyncio
async def test_read_entry_metadata():
    """read_entry()는 author와 written_at 메타데이터를 포함한다."""
    bb = SharedBlackboard()
    await bb.write("k", "v", author="researcher")
    entry = bb.read_entry("k")
    assert entry is not None
    assert entry.author == "researcher"
    assert entry.written_at is not None


@pytest.mark.asyncio
async def test_multiple_watchers_same_key():
    bb = SharedBlackboard()
    q1 = await bb.watch("k")
    q2 = await bb.watch("k")

    await bb.write("k", "broadcast", author="x")

    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1.value == e2.value == "broadcast"
