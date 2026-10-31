"""procedures 기능의 정제 후보: 같은 도구 작업 종류로 자기 일화가 세 번 성공해야 후보가 된다."""

from jarvis.memory.long_term.refine import MIN_SUCCESSES, candidates
from tests.fixtures.procedures_helpers import EDM_SCOPE, record_turn
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
from jarvis.memory import MemoryScope


async def test_candidates_need_three_own_successes_of_one_tool_type():
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    for i in range(MIN_SUCCESSES - 1):
        await record_turn(memory, i)
    await record_turn(memory, 10, failed=True)
    await record_turn(memory, 11, task="chat", steps=[])
    for i in range(3):
        await record_turn(memory, 20 + i, scope=MemoryScope(user_id="u1", agent_id="main", session_id="s9"))
    assert await memory.refinement_candidates(EDM_SCOPE) == []

    await record_turn(memory, 2)

    [c] = await memory.refinement_candidates(EDM_SCOPE)
    assert (c.task_type, c.generation, c.source) == ("lh_notice", 1, "edm:karen:lh_notice:1")
    assert [i.metadata["turn"] for i in c.evidence] == [0, 1, 2]


def test_candidates_of_no_items_is_empty():
    assert candidates([], EDM_SCOPE) == []
