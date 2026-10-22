"""주거 프로필: 사용자가 바꾼 항목만 바뀌고, 사용자마다 한 항목으로 저장된다."""

import pytest
import asyncio
from datetime import date

from jarvis.core.tools.housing.profile import HousingProfile, ProfileStore, apply_updates, from_metadata, parse_pairs
from jarvis.core.tools.housing.profile_tool import HousingProfileTool
from jarvis.core.slash.housing_cmd import make_housing_handler
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
from jarvis.core.tools.registry import ToolContext
from jarvis.memory.scope import MemoryScope

TODAY = date(2026, 10, 22)
ME = MemoryScope(user_id="u1", agent_id="karen")


def test_updates_change_only_given_fields_and_repeat_is_same():
    base = HousingProfile(homeless=True, income=60_000_000)
    once = apply_updates(base, {"연소득": "7000만", "혼인": "미혼"}, TODAY)
    assert once == HousingProfile(homeless=True, married=False, income=70_000_000)
    assert apply_updates(once, {"연소득": "7000만", "혼인": "미혼"}, TODAY) == once
    assert apply_updates(once, {"연소득": "모름"}, TODAY).income is None


def test_age_from_birth_date_or_age_as_of():
    born = HousingProfile(birth_date=date(1998, 3, 1))
    assert born.age_on(date(2026, 2, 28)) == 27 and born.age_on(date(2026, 3, 1)) == 28
    told = apply_updates(HousingProfile(), {"나이": "만 28세"}, TODAY)
    assert told.age_on(TODAY) == 28 and told.age_on(date(2028, 10, 22)) == 30


@pytest.mark.parametrize(("key", "value"), [("키", "180"), ("무주택", "글쎄"), ("생년월일", "1998")])
def test_bad_updates_raise(key, value):
    with pytest.raises(ValueError):
        apply_updates(HousingProfile(), {key: value}, TODAY)


def test_parse_pairs_and_metadata_round_trip():
    pairs = parse_pairs("연소득=6000만 혼인=미혼, 생애최초 미사용")
    assert pairs == {"연소득": "6000만", "혼인": "미혼", "생애최초": "미사용"}
    profile = apply_updates(HousingProfile(), {**pairs, "생년월일": "2000-01-01"}, TODAY)
    assert from_metadata(profile.metadata()) == profile


def _store() -> ProfileStore:
    return ProfileStore(MemoryService(InMemoryItemStore()))


def test_tool_saves_one_item_per_user_and_other_users_do_not_see_it():
    store = _store()
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
    result = asyncio.run(HousingProfileTool(_store()).execute("t1", {"action": "set", "homeless": True}))
    assert result.is_error


def test_slash_command_sets_shows_and_clears():
    handle = make_housing_handler(_store(), lambda: TODAY)

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
