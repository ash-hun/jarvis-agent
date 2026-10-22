"""[core] 사용자의 주거 프로필(대출 자격 조건)을 보고 고치고 지우는 /housing 핸들러 factory."""

from datetime import date
from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

from jarvis.core.tools.housing.profile import KNOWN, ProfileStore, apply_updates, parse_pairs
from jarvis.core.tools.housing.profile_tool import describe
from jarvis.core.tools.housing.fetch import kst_today
from jarvis.memory.scope import LOCAL_USER

if TYPE_CHECKING:
    from jarvis.memory.scope import MemoryScope

ScopedHandler = Callable[[str, "MemoryScope"], Awaitable[str]]

USAGE = (
    "[Housing] 사용법:\n"
    "  /housing                         주거 프로필 보기\n"
    "  /housing set 연소득=6000만 혼인=미혼  고치기(준 항목만)\n"
    "  /housing clear                   지우기\n"
    f"  항목: {KNOWN}. 값: 예/아니오, 금액('6000만'), 생년월일 YYYY-MM-DD, 모름(비우기)"
)


def make_housing_handler(store: ProfileStore, today: Callable[[], date] = kst_today) -> ScopedHandler:
    async def handle(args: str, scope: "MemoryScope") -> str:
        user = scope.user_id or LOCAL_USER
        sub, _, rest = args.strip().partition(" ")
        if sub in ("", "show"):
            return "[Housing] " + describe(await store.get(user), today())
        if sub == "clear":
            removed = await store.clear(user)
            return "[Housing] 지웠습니다." if removed else "[Housing] 지울 프로필이 없습니다."
        if sub != "set" or not rest.strip():
            return USAGE
        try:
            updated = apply_updates(await store.get(user), parse_pairs(rest), today())
        except ValueError as exc:
            return f"[Housing] {exc}\n{USAGE}"
        await store.save(updated, scope, today())
        return "[Housing] 저장했습니다. " + describe(updated, today())

    return handle
