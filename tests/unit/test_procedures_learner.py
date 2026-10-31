"""procedures 기능의 학습기: 같은 출처는 한 번만 증류, 이름 충돌 접미사, 계획 검사, 턴 일화 정제."""

import pytest
from dataclasses import replace

from tests.fixtures.procedures_helpers import (
    DRAFT,
    EDM_SCOPE,
    PLAN_JSON,
    CountingDistiller,
    edm_learner,
    record_turn,
    success_history,
)
from jarvis.core.procedures import STATUS_DRAFT, ProcedureLearner, ProcedureStore, find_spans, parse_draft
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


async def test_refine_distills_once_per_generation_and_keeps_agent(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    learner, store, distiller = edm_learner(tmp_path, memory)
    for i in range(3):
        await record_turn(memory, i)

    assert await learner.refine(EDM_SCOPE) == ["loan-from-notice"]
    assert await learner.refine(EDM_SCOPE) == [] and distiller.calls == 1
    [proc] = store.list()
    assert (proc.agent, proc.source, proc.status) == ("karen", "edm:karen:lh_notice:1", "draft")
    span = distiller.spans[0]
    assert span.request == "서울 공고로 대출 계산 2" and span.outcome == "계산 결과 2"
    assert [s.name for s in span.steps] == ["lh_notice", "housing_loan"]

    for i in range(3, 6):
        await record_turn(memory, i)
    written = await learner.refine(EDM_SCOPE)
    assert len(written) == 1 and written[0] != "loan-from-notice" and len(store.list()) == 2


async def test_refine_skips_candidates_without_recorded_steps(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    learner, store, distiller = edm_learner(tmp_path, memory)
    for i in range(3):
        await record_turn(memory, i, steps=[])
        item = (await memory.store.recent(EDM_SCOPE, kinds=[MemoryKind.EPISODIC], limit=1))[0]
        item.metadata["task_type"] = "lh_notice"
        await memory.store.store(item)

    assert await learner.refine(EDM_SCOPE) == [] and distiller.calls == 0 and store.list() == []
