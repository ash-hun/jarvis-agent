"""openloop: /openloop 핸들러의 목록, 완료와 무시 처리, id 오류, 사용법 안내를 검증한다."""

import pytest

from jarvis.agent_layer.openloop import InMemoryOpenLoopStore, OpenLoop
from jarvis.core.slash.openloop_cmd import make_openloop_handler


async def _store_with(*descriptions: str) -> tuple[InMemoryOpenLoopStore, list[OpenLoop]]:
    store = InMemoryOpenLoopStore()
    loops = [OpenLoop(id=f"{i:02d}abcdef0123", description=d, created_at=i) for i, d in enumerate(descriptions)]
    for loop in loops:
        await store.add(loop)
    return store, loops


@pytest.mark.parametrize(
    ("descriptions", "args", "lines"),
    [
        ((), "", ["[OpenLoop] 열린 항목이 없습니다."]),
        (
            ("보고서 보내기", "회의록 정리"),
            "list",
            ["[OpenLoop] 열린 항목:", "  - 01abcdef  회의록 정리", "  - 00abcdef  보고서 보내기"],
        ),
    ],
)
async def test_list_shows_open_items_newest_first_or_empty_notice(descriptions, args, lines):
    store, _ = await _store_with(*descriptions)

    out = await make_openloop_handler(store)(args)

    assert out.splitlines() == lines


@pytest.mark.parametrize(
    ("command", "out", "status"),
    [
        ("done 00abcdef", "[OpenLoop] 완료 처리: 보고서 보내기", "done"),
        ("dismiss 00abcdef0123", "[OpenLoop] 무시 처리: 보고서 보내기", "dismissed"),
    ],
)
async def test_status_command_closes_by_prefix_or_full_id(command, out, status):
    store, loops = await _store_with("보고서 보내기")

    result = await make_openloop_handler(store)(command)

    assert result == out
    assert (await store.get(loops[0].id)).status == status


async def test_done_twice_is_stable():
    store, loops = await _store_with("보고서 보내기")
    handle = make_openloop_handler(store)

    await handle("done 00abcdef")
    await handle("done 00abcdef")

    assert (await store.get(loops[0].id)).status == "done"


@pytest.mark.parametrize(
    ("command", "out"),
    [("done", "[OpenLoop] id가 필요합니다."), ("done zz", "[OpenLoop] 'zz' 항목을 찾을 수 없습니다.")],
)
async def test_status_command_reports_missing_or_unknown_id(command, out):
    store, _ = await _store_with("보고서 보내기")

    assert await make_openloop_handler(store)(command) == out


async def test_unknown_subcommand_shows_usage():
    out = await make_openloop_handler(InMemoryOpenLoopStore())("frobnicate")

    assert out.startswith("[OpenLoop] 추적 중인 약속/미완 작업.")
