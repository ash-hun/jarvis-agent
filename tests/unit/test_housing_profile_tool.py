"""housing: housing_profile 도구가 사용자마다 한 항목으로 저장하고 범위가 없으면 쓰지 않는지 검증."""

import asyncio
from datetime import date

from jarvis.core.tools.housing.profile import HousingProfile, ProfileStore
from jarvis.core.tools.housing.profile_tool import HousingProfileTool
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.core.tools.tools_registry import ToolContext
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.scope import MemoryScope

TODAY = date(2026, 10, 22)
ME = MemoryScope(user_id="u1", agent_id="karen")


def test_tool_saves_one_item_per_user_and_other_users_do_not_see_it():
    store = ProfileStore(MemoryService(InMemoryItemStore()))
    tool = HousingProfileTool(store, lambda: TODAY)
    context = ToolContext(scope=ME)

    async def run():
        await tool.execute("t1", {"action": "set", "homeless": True, "income": "6000만"}, context=context)
        await tool.execute("t2", {"action": "set", "married": False}, context=context)
        shown = await tool.execute("t3", {"action": "get"}, context=context)
        other = await store.get("u2")
        return shown.content[0].text, await store.get("u1"), other

    text, mine, other = asyncio.run(run())

    assert mine == HousingProfile(homeless=True, married=False, income=60_000_000)
    assert "연소득: 60,000,000원" in text and "혼인: 미혼" in text
    assert other.is_empty()


def test_tool_without_scope_does_not_write():
    tool = HousingProfileTool(ProfileStore(MemoryService(InMemoryItemStore())))

    result = asyncio.run(tool.execute("t1", {"action": "set", "homeless": True}))

    assert result.is_error
