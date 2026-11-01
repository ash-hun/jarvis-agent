"""procedures 기능: 통합(consolidate)이 실패를 반성해 초안을 남기고, 승인한 작업 패턴이 다음 요청에 들어가는 흐름."""

from tests.fixtures.procedures_helpers import EDM_SCOPE, PATTERN_FIX, ScriptedReflector, record_turn, reflect_learner
from jarvis.core.slash.procedures_cmd import make_procedures_handler
from jarvis.memory.long_term.task_pattern import PATTERN_HEADER
from jarvis.core.skills.skills_registry import SkillRegistry
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.memory.memory_service import MemoryService
from jarvis.model_layer.model_types import UserMessage

CTX = {"user_id": EDM_SCOPE.user_id, "agent_id": EDM_SCOPE.agent_id, "session_id": "s2"}


async def test_consolidate_reflects_failure_once_and_approved_pattern_reaches_next_request(tmp_path):
    memory = MemoryService(InMemoryItemStore(), stm_turns=3)
    reflector = ScriptedReflector(PATTERN_FIX)
    learner, store = reflect_learner(tmp_path, memory, reflector)
    memory.attach_refiner(learner.refine)
    await record_turn(memory, 0, failed=True)

    await memory.consolidate(EDM_SCOPE)
    await memory.consolidate(EDM_SCOPE)

    assert reflector.calls == 1
    [draft] = store.list()
    assert draft.kind == "task_pattern" and draft.status == "draft"
    blocks = await memory.observe([UserMessage(content="대출 계산해줘")], CTX)
    assert not any(PATTERN_HEADER in str(m.content) for m in blocks)

    handle = make_procedures_handler(store, ToolRegistry(), SkillRegistry(), learner=learner)
    assert "작업 패턴으로 승인" in await handle(f"approve {draft.name}", EDM_SCOPE)

    blocks = await memory.observe([UserMessage(content="대출 계산해줘")], CTX)
    assert any(PATTERN_HEADER in str(m.content) and "검산" in str(m.content) for m in blocks)
