"""procedures 기능의 /procedures 명령: 학습, 목록, 보기, 승인, 거절, 개정 교체, 작업 패턴 승인과 학습이 꺼진 경우."""

from dataclasses import replace

from tests.fixtures.procedures_helpers import DRAFT, CountingDistiller, success_history
from jarvis.core.procedures import Procedure, ProcedureLearner, ProcedureStore
from jarvis.core.slash.procedures_cmd import make_procedures_handler
from jarvis.core.skills.skills_registry import SkillRegistry
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.scope import MemoryScope

MAIN = MemoryScope(user_id="local", session_id="s1")
KAREN = MemoryScope(user_id="local", agent_id="karen", session_id="s1")


async def test_procedures_command_learns_approves_and_rejects(tmp_path, jsonl_repo):
    store = ProcedureStore(str(tmp_path))
    tools, skills = ToolRegistry(), SkillRegistry()
    learner = ProcedureLearner(store, CountingDistiller(DRAFT))
    await jsonl_repo.create(session_id="s1")
    for m in success_history():
        await jsonl_repo.append("s1", m)
    handle = make_procedures_handler(store, tools, skills, learner=learner, session_repo=jsonl_repo)

    assert "없습니다" in await handle("", MAIN)
    assert "run-tests" in await handle("learn", MAIN)
    assert "run-tests [draft]" in await handle("list", MAIN)
    assert "pytest 실행" in await handle("show run-tests", MAIN)
    assert "procedure_run-tests" in await handle("approve run-tests", MAIN)
    assert tools.get("procedure_run-tests") is not None and skills.get("run-tests") is not None
    assert "없는 절차" in await handle("approve nope", MAIN)
    assert "삭제" in await handle("reject run-tests", MAIN)
    assert tools.get("procedure_run-tests") is None and skills.get("run-tests") is None
    assert "사용법" in await handle("bogus", MAIN)


async def test_procedures_command_hides_other_agents_procedures(tmp_path, jsonl_repo):
    store = ProcedureStore(str(tmp_path))
    tools, skills = ToolRegistry(), SkillRegistry()
    await jsonl_repo.create(session_id="s1")
    for m in success_history():
        await jsonl_repo.append("s1", m)
    learner = ProcedureLearner(store, CountingDistiller(DRAFT))
    handle = make_procedures_handler(store, tools, skills, learner=learner, session_repo=jsonl_repo)
    await handle("learn", KAREN)

    assert "없습니다" in await handle("list", MAIN)
    assert "없는 절차" in await handle("approve run-tests", MAIN)
    assert "없는 절차" in await handle("reject run-tests", MAIN)
    assert store.get("run-tests") is not None and store.get("run-tests").agent == "karen"
    assert "procedure_run-tests" in await handle("approve run-tests", KAREN)
    assert skills.get("run-tests", "main") is None and skills.get("run-tests", "karen") is not None


async def test_procedures_learn_without_learner_reports_disabled(tmp_path):
    handle = make_procedures_handler(ProcedureStore(str(tmp_path)), ToolRegistry(), SkillRegistry())

    assert "꺼져" in await handle("learn", MAIN)


async def test_procedures_approve_replaces_with_revision_and_reject_drops_only_revision(tmp_path):
    store = ProcedureStore(str(tmp_path))
    tools, skills = ToolRegistry(), SkillRegistry()
    handle = make_procedures_handler(store, tools, skills)
    revision = Procedure(name="deploy", description="새", body="새 본문\n", generation=2)
    store.save(Procedure(name="deploy", description="옛", body="옛 본문\n", status="approved", generation=1,
                         revision=revision))

    assert "개정 초안 있음" in await handle("list", MAIN) and "새 본문" in await handle("show deploy", MAIN)
    assert "개정으로 교체" in await handle("approve deploy", MAIN)
    assert "새 본문" in skills.get("deploy").content and store.get("deploy").revision is None

    store.save(replace(store.get("deploy"), revision=replace(revision, body="더 새 본문\n", generation=3)))
    assert "버림" in await handle("reject deploy", MAIN)
    assert store.get("deploy").body == "새 본문\n" and store.get("deploy").revision is None


async def test_procedures_approve_task_pattern_moves_it_into_memory(tmp_path):
    store = ProcedureStore(str(tmp_path))
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    learner = ProcedureLearner(store, CountingDistiller(DRAFT), memory=memory)
    handle = make_procedures_handler(store, ToolRegistry(), SkillRegistry(), learner=learner)
    store.save(Procedure(name="pattern-verify", description="계산할 때", body="검산한다\n", agent="karen",
                         kind="task_pattern", keywords=("계산",)))

    assert "작업 패턴" in await handle("list", KAREN)
    assert "작업 패턴으로 승인" in await handle("approve pattern-verify", KAREN)

    [pattern] = await memory.task_patterns(KAREN)
    assert (pattern.name, pattern.when, pattern.steps) == ("verify", "계산할 때", "검산한다")
    assert pattern.keywords == ("계산",)
    assert store.list() == []
    no_memory = make_procedures_handler(store, ToolRegistry(), SkillRegistry())
    store.save(Procedure(name="pattern-x", description="w", body="b\n", kind="task_pattern"))
    assert "메모리" in await no_memory("approve pattern-x", MAIN)
