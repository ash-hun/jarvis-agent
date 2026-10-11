"""/openloop 슬래시 명령 핸들러 테스트."""

from jarvis.agent_layer.openloop import InMemoryOpenLoopStore, OpenLoop
from jarvis.core.slash.openloop_cmd import make_openloop_handler


async def _store_with(*descriptions: str) -> tuple[InMemoryOpenLoopStore, list[OpenLoop]]:
    store = InMemoryOpenLoopStore()
    loops = [OpenLoop(id=f"{i:02d}abcdef0123", description=d, created_at=i) for i, d in enumerate(descriptions)]
    for loop in loops:
        await store.add(loop)
    return store, loops


async def test_list_empty():
    handle = make_openloop_handler(InMemoryOpenLoopStore())
    assert await handle("") == "[OpenLoop] 열린 항목이 없습니다."


async def test_list_shows_open_items_newest_first():
    store, _ = await _store_with("보고서 보내기", "회의록 정리")
    out = await make_openloop_handler(store)("list")
    assert out.splitlines() == ["[OpenLoop] 열린 항목:", "  - 01abcdef  회의록 정리", "  - 00abcdef  보고서 보내기"]


async def test_done_by_prefix():
    store, loops = await _store_with("보고서 보내기")
    out = await make_openloop_handler(store)("done 00abcdef")
    assert out == "[OpenLoop] 완료 처리: 보고서 보내기"
    assert (await store.get(loops[0].id)).status == "done"


async def test_dismiss_by_full_id():
    store, loops = await _store_with("보고서 보내기")
    out = await make_openloop_handler(store)(f"dismiss {loops[0].id}")
    assert out == "[OpenLoop] 무시 처리: 보고서 보내기"
    assert (await store.get(loops[0].id)).status == "dismissed"


async def test_done_twice_is_stable():
    store, loops = await _store_with("보고서 보내기")
    handle = make_openloop_handler(store)
    await handle("done 00abcdef")
    await handle("done 00abcdef")
    assert (await store.get(loops[0].id)).status == "done"


async def test_missing_id_and_unknown_id():
    store, _ = await _store_with("보고서 보내기")
    handle = make_openloop_handler(store)
    assert await handle("done") == "[OpenLoop] id가 필요합니다."
    assert await handle("done zz") == "[OpenLoop] 'zz' 항목을 찾을 수 없습니다."


async def test_unknown_subcommand_shows_usage():
    out = await make_openloop_handler(InMemoryOpenLoopStore())("frobnicate")
    assert out.startswith("[OpenLoop] 추적 중인 약속/미완 작업.")
