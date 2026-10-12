"""remember_task_pattern 도구와 /patterns 명령: 부른 에이전트 범위로 저장하고 보고 지운다."""

from jarvis.core.slash.patterns_cmd import make_patterns_handler
from jarvis.core.tools.registry import ToolContext
from jarvis.core.tools.task_pattern import TaskPatternTool
from jarvis.memory import MemoryScope, MemoryService, current_scope
from jarvis.memory.stores.in_memory import InMemoryItemStore

KAREN = MemoryScope(user_id="u1", agent_id="karen", session_id="k1")
MAIN = MemoryScope(user_id="u1", agent_id="main", session_id="m1")
PARAMS = {
    "name": "예산 기반 공고 추천",
    "when": "총예산과 현금으로 공고 추천 요청",
    "steps": "대출 = 총예산 - 현금, 금리 4%",
    "keywords": "예산, 현금, 추천",
}


async def test_tool_saves_in_the_calling_agent_scope():
    memory = MemoryService(InMemoryItemStore())
    result = await TaskPatternTool(memory).execute("t1", PARAMS, context=ToolContext(scope=KAREN, session_id="k1"))
    assert not result.is_error and "karen" in result.content[0].text
    assert [p.name for p in await memory.task_patterns(KAREN)] == ["예산 기반 공고 추천"]
    assert await memory.task_patterns(MAIN) == []


async def test_tool_rejects_missing_fields():
    memory = MemoryService(InMemoryItemStore())
    result = await TaskPatternTool(memory).execute("t1", {**PARAMS, "keywords": "a"}, context=ToolContext(scope=KAREN))
    assert result.is_error
    assert await memory.task_patterns(KAREN) == []


async def test_patterns_command_lists_and_forgets_for_current_agent():
    memory = MemoryService(InMemoryItemStore())
    await TaskPatternTool(memory).execute("t1", PARAMS, context=ToolContext(scope=KAREN))
    handle = make_patterns_handler(memory)
    token = current_scope.set(MAIN)
    try:
        assert "저장된 작업 패턴이 없습니다" in await handle("")
    finally:
        current_scope.reset(token)
    token = current_scope.set(KAREN)
    try:
        assert "예산 기반 공고 추천" in await handle("")
        assert "지웠습니다" in await handle("forget 예산 기반 공고 추천")
        assert "없습니다" in await handle("forget 예산 기반 공고 추천")
        assert "사용법" in await handle("forget")
    finally:
        current_scope.reset(token)
