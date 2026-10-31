"""task_pattern: /patterns 명령이 지금 에이전트의 작업 패턴만 보여 주고 이름으로 지우는지 검증."""

from jarvis.core.slash.patterns_cmd import make_patterns_handler
from jarvis.memory.long_term.task_pattern import TaskPattern
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory import MemoryScope, MemoryService

KAREN = MemoryScope(user_id="u1", agent_id="karen", session_id="k1")
MAIN = MemoryScope(user_id="u1", agent_id="main", session_id="m1")
PATTERN = TaskPattern(
    "예산 기반 공고 추천", "총예산과 현금으로 공고 추천 요청", "대출 = 총예산 - 현금, 금리 4%", ("예산", "현금", "추천")
)


async def test_patterns_command_lists_and_forgets_for_current_agent():
    memory = MemoryService(InMemoryItemStore())
    await memory.remember_pattern(PATTERN, KAREN)
    handle = make_patterns_handler(memory)

    assert "저장된 작업 패턴이 없습니다" in await handle("", MAIN)
    assert "예산 기반 공고 추천" in await handle("", KAREN)
    assert "지웠습니다" in await handle("forget 예산 기반 공고 추천", KAREN)
    assert "없습니다" in await handle("forget 예산 기반 공고 추천", KAREN)
    assert "사용법" in await handle("forget", KAREN)
