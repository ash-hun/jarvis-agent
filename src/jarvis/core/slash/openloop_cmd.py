"""[core] 추적 중인 약속/미완 작업(open loop)을 나열하고 완료, 무시 처리하는 /openloop 핸들러 factory."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.agent_layer.openloop import OpenLoopStore

Handler = Callable[[str], Awaitable[str]]

_USAGE = (
    "[OpenLoop] 추적 중인 약속/미완 작업.\n"
    "사용법:\n"
    "  /openloop                 열린 항목 목록\n"
    "  /openloop done <id>       완료 처리\n"
    "  /openloop dismiss <id>    무시 처리"
)


def make_openloop_handler(store: OpenLoopStore) -> Handler:
    """SlashCommandDispatcher에 등록할 /openloop 핸들러 factory."""

    async def handle(args: str) -> str:
        args = args.strip()
        if not args:
            return await _handle_list(store)

        parts = args.split(None, 1)
        subcmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        if subcmd == "done":
            return await _handle_status(store, rest, "done")
        if subcmd == "dismiss":
            return await _handle_status(store, rest, "dismissed")
        if subcmd in ("list", "ls"):
            return await _handle_list(store)
        return _USAGE

    return handle


async def _handle_list(store: OpenLoopStore) -> str:
    loops = await store.list_open(limit=20)
    if not loops:
        return "[OpenLoop] 열린 항목이 없습니다."
    lines = ["[OpenLoop] 열린 항목:"]
    lines.extend(f"  - {loop.id[:8]}  {loop.description}" for loop in loops)
    return "\n".join(lines)


async def _handle_status(store: OpenLoopStore, loop_id: str, status: str) -> str:
    if not loop_id:
        return "[OpenLoop] id가 필요합니다."
    # 짧은 prefix(8자)로도 찾도록 보조. 전체/접두 일치 모두 허용.
    target = await store.get(loop_id)
    if target is None:
        for loop in await store.all():
            if loop.id.startswith(loop_id):
                target = loop
                break
    if target is None:
        return f"[OpenLoop] '{loop_id}' 항목을 찾을 수 없습니다."
    await store.update_status(target.id, status)
    label = "완료" if status == "done" else "무시"
    return f"[OpenLoop] {label} 처리: {target.description}"
