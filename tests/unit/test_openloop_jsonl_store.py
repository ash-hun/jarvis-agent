"""openloop: JSONL 저장소가 추가, 상태, 기한, 에이전트를 남겨 재로드 뒤 되살리고 바뀔 때만 덧붙이는지 검증한다."""

import json

from jarvis.agent_layer.openloop import JsonlOpenLoopStore, OpenLoop, OpenLoopStore


def test_jsonl_store_is_open_loop_store(tmp_path):
    assert isinstance(JsonlOpenLoopStore(path=str(tmp_path / "openloops.jsonl")), OpenLoopStore)


async def test_add_persists_across_reload(tmp_path):
    path = str(tmp_path / "openloops.jsonl")
    await JsonlOpenLoopStore(path=path).add(OpenLoop(description="배포 결과 공유", origin_session="s1"))

    loops = await JsonlOpenLoopStore(path=path).list_open(session_id="s1")

    assert len(loops) == 1
    assert loops[0].description == "배포 결과 공유"


async def test_status_update_persists_via_replay(tmp_path):
    path = str(tmp_path / "openloops.jsonl")
    s1 = JsonlOpenLoopStore(path=path)
    lid = await s1.add(OpenLoop(description="작업 A"))
    await s1.update_status(lid, "done")

    s2 = JsonlOpenLoopStore(path=path)

    got = await s2.get(lid)
    assert got is not None and got.status == "done"
    assert await s2.list_open() == []


async def test_add_unique_dedups_across_reload(tmp_path):
    path = str(tmp_path / "openloops.jsonl")
    await JsonlOpenLoopStore(path=path).add_unique(OpenLoop(description="같은 약속", origin_session="s1"))
    s2 = JsonlOpenLoopStore(path=path)

    dup = await s2.add_unique(OpenLoop(description="같은  약속", origin_session="s1"))

    assert dup is None
    assert len(await s2.all()) == 1


async def test_missing_file_is_empty(tmp_path):
    store = JsonlOpenLoopStore(path=str(tmp_path / "nope.jsonl"))

    assert await store.list_open() == []
    assert await store.all() == []


async def test_update_status_rejects_unknown_status_and_id(tmp_path):
    store = JsonlOpenLoopStore(path=str(tmp_path / "openloops.jsonl"))
    lid = await store.add(OpenLoop(description="x"))

    assert await store.update_status(lid, "bogus") is False
    assert await store.update_status("missing", "done") is False
    assert await store.update_status(lid, "dismissed") is True


async def test_due_update_and_expired_survive_reload(tmp_path):
    path = str(tmp_path / "openloops.jsonl")
    s1 = JsonlOpenLoopStore(path=path)
    first = await s1.add_unique(OpenLoop(description="배포 결과 공유 회의 준비", origin_session="s"))
    paraphrase = OpenLoop(description="배포 결과 공유 회의 준비 및 진행", due_ms=1000, origin_session="s")
    assert await s1.add_unique(paraphrase) == first
    other = await s1.add(OpenLoop(description="리뷰 답변", origin_session="s"))
    assert await s1.update_status(other, "expired")

    s2 = JsonlOpenLoopStore(path=path)

    assert [(x.id, x.due_ms) for x in await s2.list_open()] == [(first, 1000)]
    assert (await s2.get(other)).status == "expired"


async def test_agent_survives_reload_and_old_rows_are_main(tmp_path):
    path = tmp_path / "loops.jsonl"
    old = {"id": "old", "description": "옛 약속", "status": "open", "created_at": 1, "updated_at": 1}
    path.write_text(json.dumps(old) + "\n")
    await JsonlOpenLoopStore(path=str(path)).add(OpenLoop(description="뉴스 정리", agent_id="karen"))

    reloaded = {lp.description: lp.agent_id for lp in await JsonlOpenLoopStore(path=str(path)).all()}

    assert reloaded == {"옛 약속": "main", "뉴스 정리": "karen"}


async def test_jsonl_update_status_appends_once_per_change(tmp_path):
    path = tmp_path / "loops.jsonl"
    store = JsonlOpenLoopStore(path=str(path))
    await store.add(OpenLoop(id="x", description="약속"))

    assert await store.update_status("x", "done") is True
    assert await store.update_status("x", "bogus") is False
    assert await store.update_status("missing", "done") is False

    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
