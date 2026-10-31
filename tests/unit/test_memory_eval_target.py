"""memory_eval 기능의 평가 대상 기본 클래스: 기억 심기, 질의, 초기화."""

from jarvis.memory.eval.eval_schema import SetupStep
from jarvis.memory.eval.target import EvalTarget
from jarvis.memory import MemoryScope

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


async def test_eval_target_base_remembers_probes_and_resets():
    target = EvalTarget()
    await target.setup(SetupStep(remember="거주지: 서울"), SCOPE)
    await target.setup(SetupStep(skill="deploy", description="배포", aliases=["배포"]), SCOPE)

    assert await target.probe("거주지", SCOPE, top_k=3) == ["거주지: 서울"]
    assert await target.probe("배포", SCOPE, top_k=3, kind="procedures") == ["deploy"]
    await target.reset()
    assert await target.probe("거주지", SCOPE, top_k=3) == []
