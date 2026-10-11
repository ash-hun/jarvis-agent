"""[core] 최근 자기 성찰 저널을 보이거나 새로 쓰는 /journal 핸들러 factory."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.agent_layer.journal import ReflectionJournaler

Handler = Callable[[str], Awaitable[str]]

_USAGE = (
    "[Journal] 자기 성찰 저널 (Tier 3).\n"
    "사용법:\n"
    "  /journal           최근 저널 항목 표시\n"
    "  /journal write     사고 로그를 성찰해 새 저널 작성"
)


def make_journal_handler(journaler: ReflectionJournaler) -> Handler:
    """SlashCommandDispatcher에 등록할 /journal 핸들러 factory."""

    async def handle(args: str) -> str:
        sub = args.strip().lower()
        if sub == "write":
            entry = await journaler.write()
            if not entry:
                return "[Journal] 성찰할 사고 기록이 없습니다."
            return f"[Journal] 새 성찰:\n{entry}"
        if sub in ("", "list", "show"):
            entries = await journaler.recent(limit=5)
            if not entries:
                return "[Journal] 저널이 비어 있습니다. /journal write 로 작성하세요."
            return "[Journal] 최근 성찰:\n" + "\n".join(f"  · {e}" for e in entries)
        return _USAGE

    return handle
