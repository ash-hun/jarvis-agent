"""[core] 장기 기억을 저장, 나열, 검색, 삭제, 점검하는 /remember 핸들러 factory."""

from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.agent_layer.session.session_protocol import SessionRepo
    from jarvis.memory.memory_service import MemoryService
    from jarvis.memory.scope import MemoryScope

ScopedHandler = Callable[[str, "MemoryScope"], Awaitable[str]]

_USAGE = (
    "[Memory] 인자가 필요합니다.\n"
    "사용법:\n"
    "  /remember <내용>              장기 기억 저장\n"
    "  /remember list               최근 기억 목록 (최대 10개)\n"
    "  /remember search <키워드>     기억 검색\n"
    "  /remember forget <id>        기억 삭제\n"
    "  /remember conflicts          서로 어긋날 수 있는 사실 쌍(간섭 후보)\n"
    "  /remember reembed            임베딩 모델이 바뀐 뒤 벡터를 다시 만든다"
)


def make_remember_handler(memory: "MemoryService", session_repo: "SessionRepo | None" = None) -> ScopedHandler:
    """SlashCommandDispatcher에 등록할 /remember 핸들러 factory.

    session_repo 가 있으면 "/remember 그거" 처럼 상대 지칭으로 저장할 때 가리킨 대화를 같이 남긴다.
    """

    async def handle(args: str, scope: "MemoryScope") -> str:
        args = args.strip()

        if not args:
            return _USAGE

        parts = args.split(None, 1)
        subcmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        if subcmd == "list":
            return await _handle_list(memory, scope)
        if subcmd == "search":
            return await _handle_search(memory, scope, rest)
        if subcmd == "forget":
            return await _handle_forget(memory, rest)
        if subcmd == "conflicts":
            return await _handle_conflicts(memory, scope)
        if subcmd == "reembed":
            count = await memory.reembed(scope)
            if not count:
                return "[Memory] 다시 만들 벡터가 없습니다."
            return f"[Memory] {count}개 항목의 벡터를 다시 만들었습니다."

        return await _handle_save(memory, scope, args, session_repo)

    return handle


async def _handle_list(memory: "MemoryService", scope: "MemoryScope") -> str:
    entries = await memory.recent(scope, limit=10)
    if not entries:
        return "[Memory] 저장된 장기 기억이 없습니다."
    lines = ["[Memory] 최근 장기 기억:"]
    for e in entries:
        preview = e.content[:80] + ("..." if len(e.content) > 80 else "")
        lines.append(f"  [{e.id[:8]}] {e.created_at.strftime('%Y-%m-%d')} — {preview}")
    return "\n".join(lines)


async def _handle_search(memory: "MemoryService", scope: "MemoryScope", query: str) -> str:
    if not query:
        return "[Memory] 검색 키워드를 입력해주세요."
    entries = await memory.recall(query, scope, limit=5)
    if not entries:
        return f"[Memory] '{query}'에 해당하는 기억이 없습니다."
    lines = [f"[Memory] '{query}' 검색 결과:"]
    for e in entries:
        preview = e.content[:80] + ("..." if len(e.content) > 80 else "")
        lines.append(f"  [{e.id[:8]}] {e.created_at.strftime('%Y-%m-%d')} — {preview}")
    return "\n".join(lines)


async def _handle_forget(memory: "MemoryService", entry_id: str) -> str:
    if not entry_id:
        return "[Memory] 삭제할 기억의 id를 입력해주세요. (/remember list 에서 확인)"
    await memory.forget(entry_id)
    return f"[Memory] 기억 [{entry_id}]을 삭제했습니다."


async def _handle_save(
    memory: "MemoryService", scope: "MemoryScope", content: str, session_repo: "SessionRepo | None"
) -> str:
    from jarvis.memory.working.deixis import has_deixis, recent_exchange

    referent = None
    session_id = scope.session_id
    if session_repo is not None and session_id and has_deixis(content):
        referent = recent_exchange(await session_repo.get_messages(session_id)) or None
    entry_id = await memory.remember(content, source="explicit", scope=scope, referent=referent)
    linked = " 가리킨 대화를 함께 남겼습니다." if referent else ""
    return f"[Memory] 장기 기억에 저장했습니다. (id: {entry_id[:8]}){linked}"


async def _handle_conflicts(memory: "MemoryService", scope: "MemoryScope") -> str:
    """간섭 후보: 주제는 다른데 내용이 비슷한 사실 쌍. 사람이 보고 /remember forget 으로 정리한다."""
    from jarvis.memory.long_term.semantic import CONFLICTS_KEY
    from jarvis.memory.memory_types import MemoryKind

    items = await memory.recent(scope, kinds=[MemoryKind.SEMANTIC], limit=200)
    by_id = {i.id: i for i in items}
    seen: set[frozenset[str]] = set()
    lines: list[str] = []
    for item in items:
        for other_id in item.metadata.get(CONFLICTS_KEY, []):
            pair = frozenset((item.id, other_id))
            other = by_id.get(other_id)
            if pair in seen or other is None:
                continue
            seen.add(pair)
            lines.append(f"  [{item.id[:8]}] {item.content[:60]}\n  [{other.id[:8]}] {other.content[:60]}")
    if not lines:
        return "[Memory] 어긋나는 사실 쌍이 없습니다."
    return "[Memory] 서로 어긋날 수 있는 사실:\n" + "\n  ---\n".join(lines)
