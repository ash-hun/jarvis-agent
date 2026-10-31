"""recall_episodes 도구: 작업 종류, 성패, 기간으로 지난 턴 일화를 고르고, 범위와 입력을 검사한다."""

from datetime import datetime

from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.core.tools.episodes import RecallEpisodesTool
from jarvis.core.tools.tools_registry import ToolContext
from jarvis.memory.memory_service import MemoryService
from jarvis.memory import MemoryScope

SCOPE = MemoryScope(user_id="u1", agent_id="karen", session_id="s1")


async def _tool() -> RecallEpisodesTool:
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    rows = [
        (1, "대출 계산: 보증금 기준(가)", "housing_loan", False, "2026-10-01"),
        (2, "대출 계산: PDF 못 읽음(나)", "housing_loan", True, "2026-10-05"),
        (3, "대출 계산 얘기만(다)", "chat", False, "2026-10-06"),
    ]
    for index, text, task, failed, day in rows:
        item_id = await memory.record_turn(index, text, "답", SCOPE, task_type=task, failed=failed)
        item = await memory.get(item_id)
        assert item is not None
        item.occurred_at = datetime.fromisoformat(day)
        await memory.store.store(item)
    await memory.remember("대출 계산 사고(라)", source="thought", scope=SCOPE)
    return RecallEpisodesTool(memory)


async def _call(tool: RecallEpisodesTool, scope: MemoryScope | None = SCOPE, **params) -> tuple[str, bool]:
    result = await tool.execute("c1", params, context=ToolContext(scope=scope))
    return result.content[0].text, result.is_error


async def test_filters_by_task_type_outcome_and_inclusive_dates():
    tool = await _tool()
    text, _ = await _call(tool, query="대출 계산", task_type="housing_loan")
    assert "(가)" in text and "(나)" in text and "(다)" not in text and "(라)" not in text
    text, _ = await _call(tool, query="대출 계산", outcome="failure")
    assert "(나)" in text and "(가)" not in text
    text, _ = await _call(tool, query="대출 계산", since="2026-10-05", until="2026-10-05")
    assert "(나)" in text and "(가)" not in text and "(다)" not in text
    assert await _call(tool, query="대출 계산", task_type="weather") == ("조건에 맞는 지난 일화가 없다", False)


async def test_other_agents_and_bad_input_are_refused():
    tool = await _tool()
    text, _ = await _call(tool, MemoryScope(user_id="u1", agent_id="main"), query="대출 계산")
    assert text == "조건에 맞는 지난 일화가 없다"
    assert (await _call(tool, query="대출", since="10월"))[1]
    assert (await _call(tool, query=""))[1]
    assert (await _call(tool, None, query="대출"))[1]
    assert (await _call(tool, query="대출", outcome="maybe"))[1]
