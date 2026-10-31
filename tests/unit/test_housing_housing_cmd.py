"""housing: /housing 명령이 주거 프로필을 저장, 표시, 삭제하고 모르는 항목을 거절하는지 검증."""

import asyncio
from datetime import date

from jarvis.core.slash.housing_cmd import make_housing_handler
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.core.tools.housing.profile import ProfileStore
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.scope import MemoryScope

TODAY = date(2026, 10, 22)
ME = MemoryScope(user_id="u1", agent_id="karen")


def test_housing_command_sets_shows_and_clears():
    handle = make_housing_handler(ProfileStore(MemoryService(InMemoryItemStore())), lambda: TODAY)

    async def run():
        saved = await handle("set 연소득=6000만 혼인=미혼", ME)
        shown = await handle("", ME)
        cleared = await handle("clear", ME)
        empty = await handle("", ME)
        bad = await handle("set 키=180", ME)
        return saved, shown, cleared, empty, bad

    saved, shown, cleared, empty, bad = asyncio.run(run())

    assert "저장했습니다" in saved and "연소득: 60,000,000원" in shown
    assert "지웠습니다" in cleared and "저장된 주거 프로필이 없다" in empty
    assert "모르는 항목" in bad
