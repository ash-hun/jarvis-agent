"""procedures 기능의 /procedures 명령: 학습, 목록, 보기, 승인, 거절 흐름과 학습이 꺼진 경우."""

from tests.fixtures.procedures_helpers import DRAFT, CountingDistiller, success_history
from jarvis.core.slash.procedures_cmd import make_procedures_handler
from jarvis.core.procedures import ProcedureLearner, ProcedureStore
from jarvis.core.skills.skills_registry import SkillRegistry
from jarvis.core.tools.tools_registry import ToolRegistry


async def test_procedures_command_learns_approves_and_rejects(tmp_path, jsonl_repo):
    store = ProcedureStore(str(tmp_path))
    tools, skills = ToolRegistry(), SkillRegistry()
    learner = ProcedureLearner(store, CountingDistiller(DRAFT))
    await jsonl_repo.create(session_id="s1")
    for m in success_history():
        await jsonl_repo.append("s1", m)
    handle = make_procedures_handler(store, tools, skills, learner=learner, session_repo=jsonl_repo, session_id="s1")

    assert "없습니다" in await handle("")
    assert "run-tests" in await handle("learn")
    assert "run-tests [draft]" in await handle("list")
    assert "pytest 실행" in await handle("show run-tests")
    assert "procedure_run-tests" in await handle("approve run-tests")
    assert tools.get("procedure_run-tests") is not None and skills.get("run-tests") is not None
    assert "없는 절차" in await handle("approve nope")
    assert "삭제" in await handle("reject run-tests")
    assert tools.get("procedure_run-tests") is None and skills.get("run-tests") is None
    assert "사용법" in await handle("bogus")


async def test_procedures_learn_without_learner_reports_disabled(tmp_path):
    handle = make_procedures_handler(ProcedureStore(str(tmp_path)), ToolRegistry(), SkillRegistry())

    assert "꺼져" in await handle("learn")
