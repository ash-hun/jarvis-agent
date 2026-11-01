"""procedures 기능의 /procedures 명령: 학습, 목록, 보기, 승인, 거절 흐름과 학습이 꺼진 경우."""

from tests.fixtures.procedures_helpers import DRAFT, CountingDistiller, success_history
from jarvis.core.slash.procedures_cmd import make_procedures_handler
from jarvis.core.procedures import ProcedureLearner, ProcedureStore
from jarvis.core.skills.skills_registry import SkillRegistry
from jarvis.core.tools.tools_registry import ToolRegistry
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
