from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.agent_layer.memory.backends.protocol import LTMBackend

Handler = Callable[[str], Awaitable[str]]

_USAGE = (
    "[Memory] 인자가 필요합니다.\n"
    "사용법:\n"
    "  /remember <내용>              장기 기억 저장\n"
    "  /remember list               최근 기억 목록 (최대 10개)\n"
    "  /remember search <키워드>     기억 검색\n"
    "  /remember forget <id>        기억 삭제"
)


def make_remember_handler(ltm_backend: LTMBackend) -> Handler:
    """SlashCommandDispatcher에 등록할 /remember 핸들러 factory."""

    async def handle(args: str) -> str:
        args = args.strip()

        if not args:
            return _USAGE

        parts = args.split(None, 1)
        subcmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        if subcmd == "list":
            return await _handle_list(ltm_backend)
        if subcmd == "search":
            return await _handle_search(ltm_backend, rest)
        if subcmd == "forget":
            return await _handle_forget(ltm_backend, rest)

        return await _handle_save(ltm_backend, args)

    return handle


async def _handle_list(ltm_backend: LTMBackend) -> str:
    entries = await ltm_backend.get_recent(limit=10)
    if not entries:
        return "[Memory] 저장된 장기 기억이 없습니다."
    lines = ["[Memory] 최근 장기 기억:"]
    for e in entries:
        preview = e.content[:80] + ("..." if len(e.content) > 80 else "")
        lines.append(f"  [{e.id[:8]}] {e.created_at.strftime('%Y-%m-%d')} — {preview}")
    return "\n".join(lines)


async def _handle_search(ltm_backend: LTMBackend, query: str) -> str:
    if not query:
        return "[Memory] 검색 키워드를 입력해주세요."
    entries = await ltm_backend.search(query, limit=5)
    if not entries:
        return f"[Memory] '{query}'에 해당하는 기억이 없습니다."
    lines = [f"[Memory] '{query}' 검색 결과:"]
    for e in entries:
        preview = e.content[:80] + ("..." if len(e.content) > 80 else "")
        lines.append(f"  [{e.id[:8]}] {e.created_at.strftime('%Y-%m-%d')} — {preview}")
    return "\n".join(lines)


async def _handle_forget(ltm_backend: LTMBackend, entry_id: str) -> str:
    if not entry_id:
        return "[Memory] 삭제할 기억의 id를 입력해주세요. (/remember list 에서 확인)"
    await ltm_backend.delete(entry_id)
    return f"[Memory] 기억 [{entry_id}]을 삭제했습니다."


async def _handle_save(ltm_backend: LTMBackend, content: str) -> str:
    from jarvis.agent_layer.memory.backends.protocol import MemoryEntry

    entry = MemoryEntry(content=content, source="explicit")
    entry_id = await ltm_backend.store(entry)
    return f"[Memory] 장기 기억에 저장했습니다. (id: {entry_id[:8]})"
