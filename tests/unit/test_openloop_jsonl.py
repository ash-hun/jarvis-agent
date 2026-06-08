"""JsonlOpenLoopStore — 파일 영속화 + 재로드 복원 (Tier 2 보강)."""
from __future__ import annotations

import pytest

from jarvis.agent_layer.openloop import JsonlOpenLoopStore, OpenLoop, OpenLoopStore


def _store(tmp_path):
    return JsonlOpenLoopStore(path=str(tmp_path / "openloops.jsonl"))


def test_jsonl_store_satisfies_protocol(tmp_path):
    assert isinstance(_store(tmp_path), OpenLoopStore)


@pytest.mark.asyncio
async def test_add_persists_across_reload(tmp_path):
    path = str(tmp_path / "openloops.jsonl")
    s1 = JsonlOpenLoopStore(path=path)
    await s1.add(OpenLoop(description="배포 결과 공유", origin_session="s1"))

    # 새 인스턴스(재시작 시뮬레이션) — 파일에서 복원돼야 한다.
    s2 = JsonlOpenLoopStore(path=path)
    loops = await s2.list_open(session_id="s1")
    assert len(loops) == 1
    assert loops[0].description == "배포 결과 공유"


@pytest.mark.asyncio
async def test_status_update_persists_via_replay(tmp_path):
    path = str(tmp_path / "openloops.jsonl")
    s1 = JsonlOpenLoopStore(path=path)
    lid = await s1.add(OpenLoop(description="작업 A"))
    await s1.update_status(lid, "done")

    # 재로드 — append-log replay로 last-wins(done) 상태가 복원.
    s2 = JsonlOpenLoopStore(path=path)
    got = await s2.get(lid)
    assert got is not None and got.status == "done"
    assert await s2.list_open() == []  # done은 열린 목록에서 제외


@pytest.mark.asyncio
async def test_add_unique_dedups_across_reload(tmp_path):
    path = str(tmp_path / "openloops.jsonl")
    s1 = JsonlOpenLoopStore(path=path)
    await s1.add_unique(OpenLoop(description="같은 약속", origin_session="s1"))

    s2 = JsonlOpenLoopStore(path=path)
    dup = await s2.add_unique(OpenLoop(description="같은  약속", origin_session="s1"))
    assert dup is None
    assert len(await s2.all()) == 1


@pytest.mark.asyncio
async def test_missing_file_is_empty(tmp_path):
    s = JsonlOpenLoopStore(path=str(tmp_path / "nope.jsonl"))
    assert await s.list_open() == []
    assert await s.all() == []


@pytest.mark.asyncio
async def test_update_status_validation(tmp_path):
    s = _store(tmp_path)
    lid = await s.add(OpenLoop(description="x"))
    assert await s.update_status(lid, "bogus") is False
    assert await s.update_status("missing", "done") is False
    assert await s.update_status(lid, "dismissed") is True


def test_config_default_and_startup_builder(tmp_path, monkeypatch):
    from jarvis.config import JarvisSettings
    from jarvis.ui.tui.startup import _build_openloop_store

    settings = JarvisSettings()
    assert settings.openloop.backend == "jsonl"  # 기본 영속(jsonl)

    settings.openloop.path = str(tmp_path / "ol.jsonl")
    store = _build_openloop_store(settings)
    assert isinstance(store, JsonlOpenLoopStore)

    settings.openloop.backend = "in_memory"
    from jarvis.agent_layer.openloop import InMemoryOpenLoopStore

    assert isinstance(_build_openloop_store(settings), InMemoryOpenLoopStore)
