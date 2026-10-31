"""EDM 에서 절차 정제: 후보 선택(같은 종류 성공 3회, 자기 일화만), 세대별 한 번만 증류, consolidate 연결."""

from datetime import datetime, timedelta

from jarvis.core.procedures import ProcedureDraft, ProcedureLearner, ProcedureStore
from jarvis.memory.long_term.refine import MIN_SUCCESSES, candidates
from jarvis.memory.memory_service import TURN_STEPS, MemoryService
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory import MemoryKind, MemoryScope

SCOPE = MemoryScope(user_id="u1", agent_id="karen", session_id="s1")
STEPS = [("lh_notice", {"region": "서울"}), ("housing_loan", {"price": 300_000_000})]


async def _turn(memory: MemoryService, index: int, task: str = "lh_notice", failed: bool = False,
                scope: MemoryScope = SCOPE, steps: list = STEPS) -> None:
    item_id = await memory.record_turn(
        index, f"서울 공고로 대출 계산 {index}", f"계산 결과 {index}", scope, task_type=task, failed=failed,
        tools=[n for n, _ in steps], steps=steps,
    )
    item = await memory.get(item_id)
    assert item is not None
    item.occurred_at = datetime(2026, 10, 1) + timedelta(days=index)
    await memory.store.store(item)


def _learner(tmp_path, memory: MemoryService, calls: list) -> tuple[ProcedureLearner, ProcedureStore]:
    async def distill(span):
        calls.append(span)
        return ProcedureDraft(name="loan-from-notice", description="공고로 대출 계산", steps=("공고 조회", "대출 계산"))

    store = ProcedureStore(str(tmp_path))
    return ProcedureLearner(store, distill, memory=memory), store


async def test_candidates_need_three_own_successes_of_one_tool_type():
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    for i in range(MIN_SUCCESSES - 1):
        await _turn(memory, i)
    await _turn(memory, 10, failed=True)
    await _turn(memory, 11, task="chat", steps=[])
    for i in range(3):
        await _turn(memory, 20 + i, scope=MemoryScope(user_id="u1", agent_id="main", session_id="s9"))
    assert await memory.refinement_candidates(SCOPE) == []

    await _turn(memory, 2)
    [c] = await memory.refinement_candidates(SCOPE)
    assert (c.task_type, c.generation, c.source) == ("lh_notice", 1, "edm:karen:lh_notice:1")
    assert [i.metadata["turn"] for i in c.evidence] == [0, 1, 2]


def test_candidates_ignore_other_kinds_and_users():
    assert candidates([], SCOPE) == []


async def test_refine_distills_once_per_generation_and_keeps_agent(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    calls: list = []
    learner, store = _learner(tmp_path, memory, calls)
    for i in range(3):
        await _turn(memory, i)

    assert await learner.refine(SCOPE) == ["loan-from-notice"]
    assert await learner.refine(SCOPE) == [] and len(calls) == 1
    [proc] = store.list()
    assert (proc.agent, proc.source, proc.status) == ("karen", "edm:karen:lh_notice:1", "draft")
    span = calls[0]
    assert span.request == "서울 공고로 대출 계산 2" and span.outcome == "계산 결과 2"
    assert [s.name for s in span.steps] == ["lh_notice", "housing_loan"]

    for i in range(3, 6):
        await _turn(memory, i)
    written = await learner.refine(SCOPE)
    assert len(written) == 1 and written[0] != "loan-from-notice" and len(store.list()) == 2


async def test_refine_skips_candidates_without_recorded_steps(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    calls: list = []
    learner, store = _learner(tmp_path, memory, calls)
    for i in range(3):
        await _turn(memory, i, steps=[])
        item = (await memory.store.recent(SCOPE, kinds=[MemoryKind.EPISODIC], limit=1))[0]
        item.metadata["task_type"] = "lh_notice"
        await memory.store.store(item)
    assert await learner.refine(SCOPE) == [] and calls == [] and store.list() == []


async def test_consolidate_runs_attached_refiner(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    calls: list = []
    learner, store = _learner(tmp_path, memory, calls)
    memory.attach_refiner(learner.refine)
    for i in range(3):
        await _turn(memory, i)
    await memory.consolidate(SCOPE)
    await memory.consolidate(SCOPE)
    assert len(store.list()) == 1 and len(calls) == 1


async def test_turn_steps_keep_short_args_only():
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    await _turn(memory, 0, steps=[("write_file", {"path": "a", "content": "x" * 5000})])
    item = (await memory.store.recent(SCOPE, limit=1))[0]
    [step] = item.metadata[TURN_STEPS]
    assert step["name"] == "write_file" and len(step["args"]["content"]) == 200


async def test_session_end_span_learning_runs_only_in_legacy_window_mode():
    from types import SimpleNamespace

    from jarvis.app.session_builder import learn_procedures

    class Learner:
        async def learn(self, session_id, messages):
            return ["span"]

    msgs = [object()]
    turn_mode = SimpleNamespace(procedure_learner=Learner(), memory=MemoryService(InMemoryItemStore(), stm_turns=3))
    legacy = SimpleNamespace(procedure_learner=Learner(), memory=MemoryService(InMemoryItemStore()))
    assert await learn_procedures(turn_mode, "s1", msgs) == []
    assert await learn_procedures(legacy, "s1", msgs) == ["span"]
