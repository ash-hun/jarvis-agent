"""procedures 기능의 학습기: 같은 출처는 한 번만 증류, 작업 종류당 파일 하나로 수렴, 실패 반성과 거름망."""

import pytest
from dataclasses import replace

from tests.fixtures.procedures_helpers import (
    DRAFT,
    EDM_SCOPE,
    LOAN_DRAFT,
    PATTERN_FIX,
    PLAN_JSON,
    PROCEDURE_FIX,
    SLIP,
    CountingDistiller,
    ScriptedReflector,
    edm_learner,
    record_turn,
    reflect_learner,
    success_history,
)
from jarvis.core.procedures import STATUS_DRAFT, Procedure, ProcedureLearner, ProcedureStore, find_spans, parse_draft
from jarvis.core.procedures.learner import build_procedure, unique_name
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
from jarvis.core.procedures.plan import PlanStep
from jarvis.memory import MemoryKind


async def test_learn_twice_writes_once_without_calling_llm_again(tmp_path):
    store = ProcedureStore(str(tmp_path))
    distiller = CountingDistiller(DRAFT)
    learner = ProcedureLearner(store, distiller)

    first = await learner.learn("s1", success_history())
    second = await learner.learn("s1", success_history())

    assert (first, second) == (["run-tests"], [])
    assert distiller.calls == 1
    proc = store.get("run-tests")
    assert proc.status == STATUS_DRAFT
    assert proc.source == "s1#0"
    assert proc.tools == ("glob", "bash", "read_file")
    assert "{{args}}" in proc.body and "1. glob 로 테스트 찾기" in proc.body and "입력: 테스트 경로" in proc.body


async def test_learn_same_name_from_other_session_gets_suffix(tmp_path):
    store = ProcedureStore(str(tmp_path))
    learner = ProcedureLearner(store, CountingDistiller(DRAFT))
    await learner.learn("s1", success_history())

    written = await learner.learn("s2", success_history())

    assert len(written) == 1 and written[0].startswith("run-tests-") and written[0] != "run-tests"
    assert len(store.list()) == 2


async def test_learn_skips_when_distiller_fails(tmp_path):
    store = ProcedureStore(str(tmp_path))

    written = await ProcedureLearner(store, CountingDistiller(None)).learn("s1", success_history())

    assert written == [] and store.list() == []


def test_unique_name_keeps_own_name_and_suffixes_deterministically_on_clash():
    assert unique_name("a", "s1#0", {}) == "a"
    assert unique_name("a", "s1#0", {"a": "s1#0"}) == "a"
    other = unique_name("a", "s2#0", {"a": "s1#0"})
    assert other.startswith("a-") and other == unique_name("a", "s2#0", {"a": "s1#0"})


def test_build_procedure_keeps_plan_that_uses_task_tools_and_inputs():
    draft = parse_draft(PLAN_JSON)
    span = find_spans(success_history())[0]

    assert build_procedure(draft, span, "s1#0", "run-tests").plan == draft.plan


@pytest.mark.parametrize(
    "plan",
    [
        (*parse_draft(PLAN_JSON).plan, PlanStep("write_file", {"path": "x"})),
        (PlanStep("glob", {"pattern": "{{nope}}"}),),
    ],
    ids=["tool_not_used_in_task", "undeclared_input"],
)
def test_build_procedure_drops_plan_outside_the_task(plan):
    draft = replace(parse_draft(PLAN_JSON), plan=plan)
    span = find_spans(success_history())[0]

    assert build_procedure(draft, span, "s1#0", "x").plan == ()


async def test_refine_converges_to_one_file_per_task_type_and_revises_approved(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    learner, store, distiller = edm_learner(tmp_path, memory)
    for i in range(3):
        await record_turn(memory, i)

    assert await learner.refine(EDM_SCOPE) == ["loan-from-notice"]
    assert await learner.refine(EDM_SCOPE) == [] and distiller.calls == 1
    [proc] = store.list()
    assert (proc.agent, proc.source, proc.status, proc.generation) == ("karen", "edm:karen:lh_notice", "draft", 1)
    span = distiller.spans[0]
    assert span.request == "서울 공고로 대출 계산 2" and span.outcome == "계산 결과 2"
    assert [s.name for s in span.steps] == ["lh_notice", "housing_loan"]

    for i in range(3, 6):
        await record_turn(memory, i)
    assert await learner.refine(EDM_SCOPE) == ["loan-from-notice"]
    [proc] = store.list()
    assert (proc.generation, proc.status) == (2, "draft")

    store.approve("loan-from-notice")
    for i in range(6, 9):
        await record_turn(memory, i)
    assert await learner.refine(EDM_SCOPE) == ["loan-from-notice"]
    assert await learner.refine(EDM_SCOPE) == [] and distiller.calls == 3
    [proc] = store.list()
    assert proc.approved and proc.generation == 2 and proc.revision is not None and proc.revision.generation == 3


async def test_refine_stops_creating_at_agent_cap(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    store = ProcedureStore(str(tmp_path))
    learner = ProcedureLearner(store, CountingDistiller(LOAN_DRAFT), memory=memory, max_per_agent=1)
    for i in range(3):
        await record_turn(memory, i)
        await record_turn(memory, 10 + i, task="housing_loan")

    assert len(await learner.refine(EDM_SCOPE)) == 1
    assert len(store.list()) == 1


def test_converge_moves_old_generation_files_into_one_and_keeps_them_archived(tmp_path):
    store = ProcedureStore(str(tmp_path))
    store.save(Procedure(name="a", description="d", body="1\n", status="approved", source="edm:karen:t:1"))
    store.save(Procedure(name="a-x", description="d", body="2\n", source="edm:karen:t:2"))
    learner = ProcedureLearner(store, CountingDistiller(None))

    assert learner.converge() == 1
    assert learner.converge() == 0
    [kept] = store.list()
    assert (kept.name, kept.source, kept.generation, kept.revision.body) == ("a", "edm:karen:t", 1, "2\n")
    assert [p.name for p in (tmp_path / ".archive").iterdir()] == ["a-x.md"]


async def test_reflect_writes_procedure_draft_once_and_marks_failures(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    reflector = ScriptedReflector(PROCEDURE_FIX)
    learner, store = reflect_learner(tmp_path, memory, reflector)
    await record_turn(memory, 0, failed=True)
    await record_turn(memory, 1, failed=True)

    [outcome] = await learner.reflect(EDM_SCOPE)
    assert await learner.reflect(EDM_SCOPE) == [] and reflector.calls == 1
    assert (outcome.kind, outcome.name) == ("procedure", "loan-check")
    proc = store.get("loan-check")
    assert (proc.source, proc.status, proc.agent) == ("edm:karen:lh_notice", "draft", "karen")
    assert "공급가를 먼저" in proc.body
    assert [a.request for a in reflector.cases[0].attempts] == ["서울 공고로 대출 계산 0", "서울 공고로 대출 계산 1"]


async def test_reflect_task_pattern_goes_to_pattern_draft(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    learner, store = reflect_learner(tmp_path, memory, ScriptedReflector(PATTERN_FIX))
    await record_turn(memory, 0, failed=True)

    [outcome] = await learner.reflect(EDM_SCOPE)

    assert outcome.kind == "task_pattern"
    draft = store.get(outcome.name)
    assert draft.kind == "task_pattern" and draft.keywords == ("계산", "대출") and draft.name.startswith("pattern-")


async def test_reflect_returns_reason_once_then_records_nothing(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    wrong = PROCEDURE_FIX.model_copy(update={"action": "task_pattern"})
    reflector = ScriptedReflector(wrong, wrong)
    learner, store = reflect_learner(tmp_path, memory, reflector)
    await record_turn(memory, 0, failed=True)

    [outcome] = await learner.reflect(EDM_SCOPE)

    assert outcome.kind == "refused" and reflector.calls == 2 and store.list() == []
    assert reflector.refusals[0] == "" and "revise_procedure" in reflector.refusals[1]


async def test_reflect_accepts_corrected_second_proposal(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    reflector = ScriptedReflector(PROCEDURE_FIX.model_copy(update={"scope": "agent_behavior"}), PROCEDURE_FIX)
    learner, store = reflect_learner(tmp_path, memory, reflector)
    await record_turn(memory, 0, failed=True)

    [outcome] = await learner.reflect(EDM_SCOPE)

    assert outcome.kind == "procedure" and len(outcome.reasons) == 1 and store.get("loan-check") is not None


async def test_reflect_blocks_task_type_after_two_refused_batches(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    reflector = ScriptedReflector(None)
    learner, _ = reflect_learner(tmp_path, memory, reflector)
    for i in range(3):
        await record_turn(memory, i, failed=True)
        await learner.reflect(EDM_SCOPE)

    assert reflector.calls == 4
    await record_turn(memory, 3, failed=True)
    [outcome] = await learner.reflect(EDM_SCOPE)
    assert outcome.kind == "blocked" and reflector.calls == 4

    await record_turn(memory, 4)
    await record_turn(memory, 5, failed=True)
    await learner.reflect(EDM_SCOPE)
    assert reflector.calls == 6


async def test_reflect_caps_batches_per_tick(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    reflector = ScriptedReflector(SLIP)
    learner, _ = reflect_learner(tmp_path, memory, reflector, max_reflections=2)
    for i, task in enumerate(["a", "b", "c"]):
        await record_turn(memory, i, task=task, failed=True)

    assert [o.kind for o in await learner.reflect(EDM_SCOPE)] == ["no_change", "no_change"]
    assert [o.task_type for o in await learner.reflect(EDM_SCOPE)] == ["c"]
    assert reflector.calls == 3


async def test_reflect_on_approved_procedure_writes_revision(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    learner, store = reflect_learner(tmp_path, memory, ScriptedReflector(PROCEDURE_FIX))
    store.save(Procedure(name="loan", description="d", body="옛 본문\n", status="approved",
                         source="edm:karen:lh_notice", agent="karen", generation=1))
    await record_turn(memory, 0, failed=True)

    [outcome] = await learner.reflect(EDM_SCOPE)

    [proc] = store.list()
    assert outcome.name == "loan" and proc.body == "옛 본문\n" and "공급가를 먼저" in proc.revision.body


async def test_unguarded_reflect_applies_mismatched_action(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    wrong = PATTERN_FIX.model_copy(update={"scope": "execution_slip"})
    learner, store = reflect_learner(tmp_path, memory, ScriptedReflector(wrong), guard=False)
    await record_turn(memory, 0, failed=True)

    [outcome] = await learner.reflect(EDM_SCOPE)

    assert outcome.kind == "task_pattern" and len(store.list()) == 1


async def test_reflect_passes_overflow_evidence(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    reflector = ScriptedReflector(SLIP)
    learner, _ = reflect_learner(tmp_path, memory, reflector)
    await record_turn(memory, 0, failed=True)
    item = (await memory.store.recent(EDM_SCOPE, kinds=[MemoryKind.EPISODIC], limit=1))[0]
    item.metadata["overflow"] = True
    await memory.store.store(item)

    await learner.reflect(EDM_SCOPE)

    assert reflector.cases[0].attempts[0].overflow is True


async def test_refine_skips_candidates_without_recorded_steps(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    learner, store, distiller = edm_learner(tmp_path, memory)
    for i in range(3):
        await record_turn(memory, i, steps=[])
        item = (await memory.store.recent(EDM_SCOPE, kinds=[MemoryKind.EPISODIC], limit=1))[0]
        item.metadata["task_type"] = "lh_notice"
        await memory.store.store(item)

    assert await learner.refine(EDM_SCOPE) == [] and distiller.calls == 0 and store.list() == []
