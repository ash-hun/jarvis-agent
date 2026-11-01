"""procedures 기능의 정제 후보: 세 번 성공한 작업 종류는 증류 후보, 반성하지 않은 실패는 반성 묶음이 된다."""

from jarvis.memory.long_term.refine import MAX_BATCH, MIN_SUCCESSES, candidates, failures, refusal_streak
from tests.fixtures.procedures_helpers import EDM_SCOPE, record_turn
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
from jarvis.memory import MemoryKind, MemoryScope


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
    assert (c.task_type, c.generation, c.source) == ("lh_notice", 1, "edm:karen:lh_notice")
    assert [i.metadata["turn"] for i in c.evidence] == [0, 1, 2]


def test_candidates_of_no_items_is_empty():
    assert candidates([], EDM_SCOPE) == []


async def test_failures_group_unreflected_own_tool_failures_newest_first_capped():
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    for i in range(MAX_BATCH + 1):
        await record_turn(memory, i, failed=True)
    await record_turn(memory, 10, task="chat", steps=[], failed=True)
    await record_turn(memory, 11)
    items = await memory.store.recent(EDM_SCOPE, kinds=[MemoryKind.EPISODIC], limit=50)

    [batch] = failures(items, EDM_SCOPE)

    assert (batch.task_type, batch.source, batch.blocked) == ("lh_notice", "edm:karen:lh_notice", False)
    assert [i.metadata["turn"] for i in batch.evidence] == [1, 2, 3]


def test_failures_and_streak_of_no_items_are_empty():
    assert failures([], EDM_SCOPE) == []
    assert refusal_streak([], []) == 0
